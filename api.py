from fastapi import FastAPI
from pydantic import BaseModel
import json
from structured_URL_generator import (
parser, define_urlConstructor_chain, fetch_openproject_data,
    build_read_request, build_create_request, build_update_request, safe_write,
    project_patch, workpack_patch,
)
from debug import debug_log
from response_generator import define_response_chain
from json_pruning import PAGE_SIZE, clean_and_remodel_json, pagination_warning
from permissions import (
    check_permission, permission_scope, project_of_work_package, refusal_answer, refusal_for,
)

import time

app = FastAPI()

class requestStructure(BaseModel):
    username: str
    question: str
    model_name_phase1: str
    model_name_phase2: str
    api_key: str


def intent_identifier(json_data, api_key):
    """ builds the right request based on the intent extracted by the model. The schema's default intent is read """
    intent = json_data.get('intent') if isinstance(json_data, dict) else None

    if intent == 'read' or intent is None:
        return build_read_request(json_data, api_key)
    if intent == 'create':
        return build_create_request(json_data, api_key)
    if intent == 'update':
        return build_update_request(json_data, api_key)

    return f"System Info: unknown intent '{intent}'"


def single(value):
    """ the extraction schema wraps every value in a list, a sentence needs the value itself """
    return value[0] if isinstance(value, list) and value else value


def write_notice(extraction, result):
    """ what phase 2 receives when a write has been validated but not committed.
    A validated write comes back as {method, url, body, ready_to_commit}: everything needed to
    perform the real request but nothing that can be turned into a sentence for the response """

    notice = {
        "intent": extraction.get("intent"),
        "macro_section": extraction.get("macro_section"),
        "ready_to_commit": result.get("ready_to_commit", False),
        "payload": {k: single(v) for k, v in (extraction.get("payload") or {}).items()},
    }

    #for an update the filters hold the selector of the target, for a create they are empty
    selector = {k: single(v) for k, v in (extraction.get("filters") or {}).items()}
    if selector:
        notice["target"] = selector

    return notice


def phase2_context(extraction, final_data):
    """ the exact string the second model receives.

    One definition, two callers: the /ask handler and the Phase 3 runner. If the runner built its
    own version, the campaign would be measuring a context slightly different from the one the
    system really produces, and nothing would ever point it out. """
    if isinstance(final_data, dict) and final_data.get('ready_to_commit'):
        return json.dumps(write_notice(extraction, final_data), indent=2)
    if isinstance(final_data, dict):
        return json.dumps(final_data, indent=2)
    return str(final_data)


def permission_guard(json_data, username, api_key):
    """ first level of the guard, BEFORE the request is built: the model has said what it wants to
    do, and Python decides whether it may. A refusal here means OpenProject is never contacted """
    if not isinstance(json_data, dict):
        return None

    data = json_data.get('properties', json_data) if 'properties' in json_data else json_data
    intent = data.get('intent') or 'read'
    section = data.get('macro_section')
    if section not in ('work_packages', 'projects'):
        return None

    project_id, project_label = permission_scope(data, api_key)
    allowed, reason = check_permission(username, intent, section, project_id, project_label)
    if allowed:
        return None
    return refusal_for(reason)


def update_scope_guard(get_response, username, api_key):
    """ second level, AFTER the read-then-write GET. Runs before the PATCH is validated, so a refusal still writes nothing """
    project_id, project_title = project_of_work_package(get_response)
    if project_id is None:
        return None

    allowed, reason = check_permission(username, "update", "work_packages",
                                       project_id, project_title)
    if allowed:
        return None
    return refusal_for(reason)


def execute(json_data, username, api_key):
    """ identifies the intent and executes it, once the user is allowed to """
    refusal = permission_guard(json_data, username, api_key)
    if refusal:
        return refusal

    request = intent_identifier(json_data, api_key)

    #if it's a string it means that it's a System Info
    if isinstance(request, str):
        return request

    #a patch_target means the intent is an update (read then write, the PATCH needs the lockVersion)
    if "patch_target" in request:
        get_response = fetch_openproject_data(request["url"], api_key)

        #the project of a work package is only known now: second level of the guard
        if request["patch_target"] == "work_package":
            refusal = update_scope_guard(get_response, username, api_key)
            if refusal:
                return refusal

        patch_function = project_patch if request["patch_target"] == "project" else workpack_patch
        patch_request = patch_function(get_response, request["payload"], request["url"], api_key)
        return safe_write(patch_request, api_key)

    #a GET without a patch_target is a read
    if request["method"] == "GET":
        data = fetch_openproject_data(request["url"], api_key)
        return clean_and_remodel_json(data)

    #the intent is a creation (a simple write)
    return safe_write(request, api_key)


@app.post("/ask")
async def ask_agent(request: requestStructure):
    start_time = time.perf_counter()
    t_phase1 = t_openproject = t_phase2 = None

    try:
        #creation of the chains for the 2 models
        url_constructur_chain = define_urlConstructor_chain(request.model_name_phase1)
        response_chain = define_response_chain(request.model_name_phase2)

        mark = time.perf_counter()
        json_params = url_constructur_chain.invoke({"format_instructions": parser.get_format_instructions(),
                                    "user_query": request.question})
        t_phase1 = round(time.perf_counter() - mark, 2)
        debug_log("json_params (Fase 1)", json_params)

        #the identity travels as a Python argument, never inside the prompt of phase 1
        mark = time.perf_counter()
        final_data = execute(json_params, request.username, request.api_key)
        t_openproject = round(time.perf_counter() - mark, 2)
        debug_log("final_data (execute)", final_data)

        #a permission refusal does NOT go through the second model, the sentence is
        #written here: deterministic, because a refusal is the one output where being
        #wrong is a security property and not a quality one
        refusal = refusal_answer(final_data)
        if refusal is not None:
            return {
                "model_choosen_phase1": request.model_name_phase1,
                "model_choosen_phase2": None,   #not invoked: the refusal is not generated
                "execution_time": round(time.perf_counter() - start_time, 2),
                "timings": {"phase1": t_phase1, "openproject": t_openproject, "phase2": None},
                "answer": refusal,
            }

        #three possible shapes reach the second model: a validated write, a read, or a plain
        #"System Info" string when something was refused
        json_data = phase2_context(json_params, final_data)

        mark = time.perf_counter()
        response = response_chain.invoke({'json' : json_data,
          'user_query' : request.question
        })
        t_phase2 = round(time.perf_counter() - mark, 2)

        #the truncation notice is appended here
        warning = pagination_warning(final_data)
        if warning:
            response = f"{response.rstrip()} {warning}"

        execution_time = round(time.perf_counter() - start_time, 2) #whole request, end to end

        return {
            "model_choosen_phase1": request.model_name_phase1,
            "model_choosen_phase2": request.model_name_phase2,
            "execution_time": execution_time,
            "timings": {"phase1": t_phase1, "openproject": t_openproject, "phase2": t_phase2},
            "answer": response
        }

    except Exception as e:
        return f"System Info: the request could not be completed, error: {e}"

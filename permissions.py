"""
check_permission(): may this identity perform this operation on this project?

The answer comes from GET /api/v3/capabilities, asked with the user's own key. decide_permission()
is the pure logic and is what the unit tests exercise, check_permission() fetches and delegates.
"""

import json

import requests

from accounts import get_account, api_key_for, project_id_for
from request_helpers import API_V3, LookupFailed, create_ID_map
from structural_validation import normalize_value

#the context in which permissions that do not live inside a project are granted
GLOBAL_CONTEXT = "global"

#mapping intent, macro_section -> the name OpenProject gives to that action
ACTION_BY_INTENT = {
    ("read", "work_packages"): "work_packages/read",
    ("create", "work_packages"): "work_packages/create",
    ("update", "work_packages"): "work_packages/update",
    ("read", "projects"): None,
    ("create", "projects"): "projects/create",
    ("update", "projects"): "projects/update",
}

#actions granted globally rather than inside a project, only the admin holds 'projects/create' and it appears
GLOBAL_ACTIONS = {"projects/create"}

#our internal token turned into something a sentence can be built from
SECTION_LABEL = {"work_packages": "work packages", "projects": "projects"}

VERIFICATION_FAILED = "could not reach OpenProject to verify permissions"

#how many capabilities we accept in one page
CAPABILITIES_PAGE_SIZE = 1000

#capabilities are stable for the length of a run
_CAPABILITIES_CACHE = {}


def clear_capabilities_cache():
    """tests and the manual scripts call this to force a fresh read from OpenProject"""
    _CAPABILITIES_CACHE.clear()


def context_key(href):
    """'/api/v3/projects/5' -> '5' ; '.../capabilities/contexts/global' -> 'global'"""
    if not href:
        return None
    if "/projects/" in href:
        return href.rstrip("/").rsplit("/", 1)[-1]
    if href.rstrip("/").endswith("global"):
        return GLOBAL_CONTEXT
    return href


def action_name(element):
    """ full action name, such as 'work_packages/create' """
    href = (element.get("_links", {}).get("action", {}) or {}).get("href", "")
    marker = "/actions/"
    if marker in href:
        return href.split(marker, 1)[1]
    parts = (element.get("id") or "").split("/")
    if len(parts) >= 3:
        return "/".join(parts[:-1])
    return href or element.get("id") or ""


def fetch_capabilities(op_user_id, api_key, use_cache=True):
    """ {context: set(actions)} for one user, asked with that user own key """
    if use_cache and op_user_id in _CAPABILITIES_CACHE:
        return _CAPABILITIES_CACHE[op_user_id]

    filters = json.dumps([{"principal": {"operator": "=", "values": [str(op_user_id)]}}])
    try:
        response = requests.get(
            API_V3 + "capabilities",
            params={"filters": filters, "pageSize": CAPABILITIES_PAGE_SIZE},
            auth=("apikey", api_key),
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    elements = data.get("_embedded", {}).get("elements", [])
    if (data.get("total") or 0) > len(elements):
        #Cannot happen with CAPABILITIES_PAGE_SIZE as declared above
        print(f"[permissions] capabilities truncated for user {op_user_id}: "
              f"{len(elements)} of {data.get('total')}, over CAPABILITIES_PAGE_SIZE="
              f"{CAPABILITIES_PAGE_SIZE}. Refusing to decide on a partial permission set.")
        return None

    capabilities = {}
    for element in elements:
        context = context_key((element.get("_links", {}).get("context", {}) or {}).get("href"))
        action = action_name(element)
        if context and action:
            capabilities.setdefault(context, set()).add(action)

    if use_cache:
        _CAPABILITIES_CACHE[op_user_id] = capabilities
    return capabilities


def decide_permission(capabilities, username, intent, macro_section, project=None,
                      project_name=None):
    """ the whole decision, with no network access """
    label = project_name or (f"project {project}" if project is not None else "this instance")
    section = SECTION_LABEL.get(macro_section, macro_section)

    #out_of_scope never gets here
    if macro_section not in ("work_packages", "projects"):
        return True, None

    if (intent, macro_section) not in ACTION_BY_INTENT:
        return False, f"unsupported operation '{intent}' on '{macro_section}'"

    action = ACTION_BY_INTENT[(intent, macro_section)]

    #creating a project is granted globally, not inside a project
    if action in GLOBAL_ACTIONS:
        if action in capabilities.get(GLOBAL_CONTEXT, set()):
            return True, None
        return False, f"user '{username}' is not allowed to create projects on this instance"

    #no project to check
    if project is None:
        if action is None:
            return True, None
        anywhere = any(action in actions for context, actions in capabilities.items()
                       if context != GLOBAL_CONTEXT)
        if anywhere:
            return True, None
        return False, f"user '{username}' is not allowed to {intent} {section} anywhere"

    context = str(project)
    if context not in capabilities:
        #the user cannot see this project at all
        return False, f"user '{username}' has no access to {label}"

    #reading a project only requires being able to see it, which the check above established
    if action is None:
        return True, None

    if action in capabilities[context]:
        return True, None
    return False, f"user '{username}' is not allowed to {intent} {section} in {label}"


def check_permission(username, intent, macro_section, project=None, project_name=None,
                     capabilities=None):
    """ the entry point called between the extraction and the request builder """
    account = get_account(username)
    if account is None:
        return False, f"unknown user '{username}'"

    if capabilities is None:
        api_key = api_key_for(username)
        if not api_key:
            return False, f"no credential available for user '{username}'"

        capabilities = fetch_capabilities(account["op_user_id"], api_key)
        if capabilities is None:
            #worded so that the gate classifies it as a transport error and blocks the cell
            return False, VERIFICATION_FAILED

    return decide_permission(capabilities, username, intent, macro_section, project, project_name)


#which project is this request about
def resolve_project_id(project_name, api_key=None):
    """ project name to numeric id """
    if project_name is None:
        return None

    project_id = project_id_for(project_name)
    if project_id is not None:
        return project_id

    if api_key:
        try:
            id_map = create_ID_map('project', api_key)
        except LookupFailed:
            #we could not resolve the name
            return None
        return id_map.get(normalize_value(project_name))
    return None


def permission_scope(json_data, api_key=None):
    """ (project_id, project_label) for an extraction, or (None, None) when there is no project to check and only the """
    if not isinstance(json_data, dict):
        return None, None
    if 'properties' in json_data:
        json_data = json_data['properties']

    intent = json_data.get('intent') or 'read'
    section = json_data.get('macro_section')
    filters = json_data.get('filters') or {}
    payload = json_data.get('payload') or {}

    if section == 'projects':
        if intent == 'create':
            return None, None
        #a project is selected by its own id or by its name
        if filters.get('id'):
            return str(filters['id'][0]), None
        if filters.get('name'):
            name = filters['name'][0]
            return resolve_project_id(name, api_key), name
        return None, None

    #work packages
    values = payload.get('project') if intent == 'create' else filters.get('project')
    if values:
        name = values[0]
        return resolve_project_id(name, api_key), name

    return None, None


def project_of_work_package(get_response):
    """ (project_id, project_title) read from a work package fetched from OpenProject """
    if not isinstance(get_response, dict):
        return None, None
    link = (get_response.get('_links', {}) or {}).get('project', {}) or {}
    href = link.get('href')
    if not href:
        return None, None
    return href.rstrip('/').rsplit('/', 1)[-1], link.get('title')


#how a refusal is written, and read back

PERMISSION_DENIED_PREFIX = "System Info: permission denied, "
PERMISSION_DENIED = PERMISSION_DENIED_PREFIX + "{reason}."


def refusal_for(reason):
    """ the system message produced by a denied check """
    if reason == VERIFICATION_FAILED:
        return f"System Info: {reason}."
    return PERMISSION_DENIED.format(reason=reason)


def refusal_answer(final_data):
    """ the sentence a refused request produces, or None when this is not a refusal """
    if isinstance(final_data, str) and final_data.startswith(PERMISSION_DENIED_PREFIX):
        return denial_sentence(final_data[len(PERMISSION_DENIED_PREFIX):].rstrip("."))
    return None


#the sentence the user reads
def denial_sentence(reason):
    """ the refusal in natural language, written by us and not generated by a model """
    if reason.startswith("unknown user") or reason.startswith("no credential"):
        return "I'm sorry, I could not recognise your account, so I cannot act on your behalf."

    marker = "is not allowed to "
    if marker in reason:
        #"...is not allowed to update work packages anywhere" -> the verb was refused everywhere, and "anywhere" reads
        action = reason.split(marker, 1)[1].replace(" anywhere", "")
        return f"I'm sorry, you don't have permission to {action}."

    marker = "has no access to "
    if marker in reason:
        return f"I'm sorry, you don't have access to {reason.split(marker, 1)[1]}."

    if reason.startswith("unsupported operation"):
        return "I'm sorry, I can't perform that operation on this kind of item."

    return "I'm sorry, you don't have permission to perform this operation."

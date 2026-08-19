import json
import requests
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from llm_builder import build_llm
from structural_validation import normalize_value, schema_validation, resolve_date_filter, DATE_FIELDS
from json_pruning import PAGE_SIZE
from debug import debug_log
from request_helpers import (
    API_V3, http_error_message, LookupFailed,
    create_ID_map, validate_project_selector, validate_workpack_selector,
    workpack_body_builder, project_body_builder,
    project_patch, workpack_patch,
    safe_write
)

#definition of the JSON structure that the LLM should return
class QueryParams(BaseModel):
    reasoning: str = Field(description="scope, intent and macro-section, decided BEFORE answering")
    intent: str = Field(description="exactly 'read', 'create' or 'update'")
    macro_section: str = Field(description="exactly 'projects', 'work_packages' or 'out_of_scope'")
    filters: dict = Field(description="search parameters (read) or target selector (update). Every value is a list",
                          examples=[{'priority': ['Low', 'High']}, {'dueDate': ['today']}])
    payload: dict = Field(default_factory=dict,
                          description="fields to write (create/update), empty for read. Every value is a list",
                          examples=[{'subject': ['Rotate the API keys'], 'type': ['Task']}])

PROMPT_VERSION = "v2-verbose"

#structured template that uses the Chain of Thought
template = """You are an API semantic extractor for a project management tool.
Your ONLY task is to turn the user query into parameters. DO NOT generate URLs.
Output ONLY a valid JSON object matching the requested schema.

TWO RULES THAT OVERRIDE EVERYTHING ELSE:
R1. NEVER invent a value. Every value you output must appear in the USER QUERY. If a field is not mentioned, LEAVE IT OUT. An extra field is an error exactly like a missing one.
R2. The examples below teach you the FORMAT, never the CONTENT. Never copy a name, a date, a priority or a project from an example into your answer.

Answer by deciding three things in this order, and say each one in 'reasoning'.

STEP 1 - IS IT IN SCOPE? This tool does exactly one thing: it reads, creates and updates PROJECTS and WORK PACKAGES (tasks, bugs, features, milestones), using only the fields listed further down.
Everything else is out of scope: weather, general knowledge, recommendations, chit-chat, users and accounts, permissions, time entries and logged hours, costs and budgets, meetings, attachments, wiki pages, categories, custom fields, and deleting or exporting anything.
If it is NOT in scope: macro_section = 'out_of_scope', intent = 'read', filters = {{}} and payload = {{}}. Nothing else.
Do not force an out-of-scope question into a filter: if the query is about the weather in Rome, 'Rome' is NOT a project name.

STEP 2 - WHICH INTENT?
- 'read': the user is asking a question or looking something up. This is the DEFAULT.
- 'create': the user wants a NEW project or work package to exist.
- 'update': the user wants an EXISTING project or work package to change. Activating, deactivating, archiving, renaming, closing, reassigning and rescheduling are ALL updates, never out of scope.

STEP 3 - WHICH MACRO-SECTION? Ask what the user wants BACK, not which words appear in the query.
- 'work_packages' if the answer is a list of tasks, bugs, features, milestones or WORK PACKAGES. The words "in the X project" only say WHERE to look: they do NOT make it 'projects'.
- 'projects' if the answer is one or more projects themselves, including their details or settings.
Both sections have an 'id' filter: an id alone tells you NOTHING about the section. "work package 3" is 'work_packages', "the project with id 3" is 'projects'.

FILTERS vs PAYLOAD: They are never both non-empty
- For 'read': 'filters' holds the search parameters, 'payload' is an empty object {{}}.
- For 'create': 'filters' is an empty object {{}}, 'payload' holds the fields of the new item.
- For 'update': 'filters' holds ONLY the selector of the target item, 'payload' holds the fields to change. The selector is the 'id'; for a project it can also be its 'name' when the user names the project instead of numbering it.

FIELDS FOR 'projects' (all usable in filters and in payload):
- 'active': 't' or 'f'. The project is running. "archive"/"deactivate" -> 'f'
- 'public': 't' or 'f'. The project is visible to everyone. "private" -> 'f'. NOT the same as 'active'
- 'name': the project name ('name' is REQUIRED to create a project)
- 'id': the project number (filters only)
- 'description': free text (payload only)

FIELDS FOR 'work_packages':
- 'author': who CREATED or OPENED it. "created by X" is ALWAYS 'author', NEVER 'assignee'. Filters only, never writable
- 'assignee': who it is ASSIGNED to, who works on it
- 'priority': 'Low', 'Normal', 'High' or 'Immediate'
- 'status': e.g. 'New', 'In progress', 'Confirmed', 'Closed'
- 'id': the work package number (filters only)
- 'subject': its title
- 'description': free text
- 'type': 'Task', 'Bug', 'Feature' or 'Milestone', ALWAYS singular
- 'version': the sprint or backlog it belongs to
- 'project': the project it lives in
- 'percentageDone': '0' to '100'. Filters only, never writable
- 'startDate' / 'dueDate': when it starts / its deadline. See DATE VALUES

DATE VALUES: never compute or guess a date, and never fill one date from the other. 'startDate' and 'dueDate' are independent: if only one is mentioned, output only that one.
- one explicit date -> ["2026-09-15"]     - a range -> ["2026-09-01", "2026-09-30"]
- "today" -> ["today"]                    - "this week" -> ["this week"]
Dates are written YYYY-MM-DD. 'today' and 'this week' are keywords, allowed in filters only: in a payload a date is always explicit.

MULTIPLE VALUES: ALL values in 'filters' and 'payload' are lists, even with one item. If one word covers several values (e.g. "urgent" means priority High AND Immediate), put them all in the list.

The examples show the FORMAT. Their names, dates and priorities belong to them, not to your answer (rule R2).

EXAMPLE 1 (read, work packages found inside a project):
User: "Find urgent milestones assigned to Sara Neri in the Zephyr project"
Output: {{"reasoning": "In scope. Read. The answer is a list of milestones, so the section is work_packages: 'in the Zephyr project' only says where to look. 'urgent' means priority High and Immediate.", "intent": "read", "macro_section": "work_packages", "filters": {{"type": ["Milestone"], "priority": ["Immediate", "High"], "assignee": ["Sara Neri"], "project": ["Zephyr"]}}, "payload": {{}}}}

EXAMPLE 2 (read, the project itself, selected by id):
User: "Show me the details of the project with id 12"
Output: {{"reasoning": "In scope. Read. The answer is a project, not its tasks, so the section is projects. The id refers to the project.", "intent": "read", "macro_section": "projects", "filters": {{"id": ["12"]}}, "payload": {{}}}}

EXAMPLE 3 (create, only what was actually said):
User: "Create a task titled 'Rotate the API keys' in the Zephyr project"
Output: {{"reasoning": "In scope. Create. Subject, type and project were given. No assignee, no priority and no date were mentioned, so I add none of them (rule R1).", "intent": "create", "macro_section": "work_packages", "filters": {{}}, "payload": {{"subject": ["Rotate the API keys"], "type": ["Task"], "project": ["Zephyr"]}}}}

EXAMPLE 4 (update a work package by id):
User: "Mark task 321 as Closed"
Output: {{"reasoning": "In scope. Update of an existing work package selected by id 321. Only the status changes.", "intent": "update", "macro_section": "work_packages", "filters": {{"id": ["321"]}}, "payload": {{"status": ["Closed"]}}}}

EXAMPLE 5 (update a project selected by name):
User: "Deactivate the Zephyr project"
Output: {{"reasoning": "In scope. Deactivating is a change to an existing project, so it is an update, not out of scope. The user names the project instead of numbering it, so the selector is the name.", "intent": "update", "macro_section": "projects", "filters": {{"name": ["Zephyr"]}}, "payload": {{"active": ["f"]}}}}

EXAMPLE 6 (read, date keyword):
User: "Which work packages are due today?"
Output: {{"reasoning": "In scope. Read. 'today' is a keyword the API resolves, not a date to compute.", "intent": "read", "macro_section": "work_packages", "filters": {{"dueDate": ["today"]}}, "payload": {{}}}}

EXAMPLE 7 (out of scope, nothing to do with projects or work packages):
User: "Who won the championship last year?"
Output: {{"reasoning": "This is general knowledge, not a project or a work package. Out of scope, so filters and payload stay empty and nothing is turned into a name filter.", "intent": "read", "macro_section": "out_of_scope", "filters": {{}}, "payload": {{}}}}

EXAMPLE 8 (out of scope, right entity but unsupported action):
User: "Export the Zephyr project tasks to Excel"
Output: {{"reasoning": "It does name a project and its tasks, but exporting is not one of the supported actions (read, create, update), so it is out of scope.", "intent": "read", "macro_section": "out_of_scope", "filters": {{}}, "payload": {{}}}}

{format_instructions}

User query: {user_query}
"""

#setting of the parser and creation of the chain
parser = JsonOutputParser(pydantic_object=QueryParams)
prompt = ChatPromptTemplate.from_template(template)

def define_urlConstructor_chain(model_name):
    llm = build_llm("phase1", model_name)
    chain = prompt | llm | parser

    return chain

ALLOWED_MACRO_SECTIONS = {"projects", "work_packages"}

#function to construct the request for the READ intent
def build_read_request(json_data, api_key) -> dict:
    if isinstance(json_data, dict) and 'properties' in json_data: #all the data are stored by default in the section properties of the json
        json_data = json_data['properties']

    if not schema_validation(json_data):
        return "System Info: query failed, data shape not valid"

    #checks if macro_section is a valid possibility
    macro_sect = json_data['macro_section']
    if macro_sect == 'out_of_scope':
        return "System Info: operation not allowed, query out of domain."
    if macro_sect not in ALLOWED_MACRO_SECTIONS:
        return f"System Info: unknown macro-section '{macro_sect}'."

    #if it is valid then creates the first part of the request
    base_url = API_V3 + f'{macro_sect}'

    #extracts the filters
    filters = json_data['filters']

    #creates a dictionary only if the filter needs it (some filters need to be searched by their corresponding ID)
    f_need_map = ['author', 'assignee', 'priority', 'status', 'type', 'version', 'project']

    op_filters = []
    missing_entities = []

    for key, val_list in filters.items():
        mapped_values = []
        operator = '='

        #rule for open and closed statuses, it manages the case and then goes on with the next filter
        if key == 'status':
            is_open = any(normalize_value(v) == 'open' for v in val_list)
            is_closed = any(normalize_value(v) == 'closed' for v in val_list)

            if is_open or is_closed:
                if len(val_list) > 1:
                    missing_entities.append(
                        f"cannot combine 'open'/'closed' with other status values in the same "
                        f"request: {val_list}")
                    continue
                operator_code = "o" if is_open else "c"
                op_filters.append({key: {"operator": operator_code, "values": []}})
                continue

        #rule for date filters (startDate/dueDate): operator deduced from the shape of the list
        if key in DATE_FIELDS:
            operator_code, mapped_dates, date_error = resolve_date_filter(val_list)
            if date_error:
                missing_entities.append(f"'{key}': {date_error}")
                continue
            op_filters.append({key: {"operator": operator_code, "values": mapped_dates}})
            continue

        if key in f_need_map:
            try:
                dict_f = create_ID_map(key, api_key) #creates the dictionary only if it's needed
            except LookupFailed as failure:
                return failure.system_info

            #every key has a list (it can be null, of 1 element or more)
            for v in val_list:
                clean_v = normalize_value(v)
                entity_id = dict_f.get(clean_v)

                if entity_id is not None:
                    mapped_values.append(str(entity_id))
                else:
                    missing_entities.append(f"'value: {v}' for the parameter {key}")

        elif key in ['subject', 'name']:
            operator = '~' #operator to search the specific name

            for v in val_list:
                mapped_values.append(str(v).strip()) #doesn't need cleaning 'cause the name MUST be equal (with Uppers and lowers)

        else:
            for v in val_list:
                if key == 'id':
                    try:
                        mapped_values.append(int(v)) #covers cases where the number of the id is not saved as an int
                    except (TypeError, ValueError):
                        missing_entities.append(f"'value: {v}' is not a valid numeric id")
                else:
                    mapped_values.append(normalize_value(v))

        if mapped_values: #if the list is not empty appends the final part of the url containing the operator and the corrisponding values
            op_filters.append({key: {"operator": operator, "values": mapped_values}})

    #if there's at least ONE error it interrupts the creation of the filter
    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist. {errors}."

    #pageSize and sortBy ALWAYS applied
    params = {"pageSize": str(PAGE_SIZE), "sortBy": '[["createdAt","desc"]]'}
    if op_filters:
        params["filters"] = json.dumps(op_filters)

    req = requests.Request('GET', base_url, params=params)
    final_url = req.prepare().url

    return {"method": "GET", "url": final_url}


#function to construct the request for the CREATE intent
def build_create_request(json_data, api_key) -> dict:
    if isinstance(json_data, dict) and 'properties' in json_data:
        json_data = json_data['properties']

    if not schema_validation(json_data):
        return "System Info: create failed, malformed extraction."

    #checks if macro_section is a valid possibility
    macro_section = json_data['macro_section']
    if macro_section == 'out_of_scope':
        return "System Info: operation not allowed, query out of domain."
    if macro_section not in ALLOWED_MACRO_SECTIONS:
        return "System Info: create is only supported for projects or work packages."

    payload = json_data['payload']
    if not payload:
        return "System Info: no fields provided to create the item."

    if macro_section == 'projects':
        body, missing_entities = project_body_builder(payload)   # no lookups: nothing to fail
        if missing_entities:
            errors = ", ".join(missing_entities)
            return f"System Info: these entities requested by the user do not exist. {errors}."
        if 'name' not in body:
            return "System Info: a project name is required to create a project."
        return {"method": "POST", "url": f"{API_V3}projects", "body": body}

    #macro_section is type work_packages
    project_values = payload.get('project')
    if not project_values:
        return "System Info: a project must be specified to create a work package."

    #checks if the project exists
    project_name = project_values[0]
    try:
        project_map = create_ID_map('project', api_key)
        project_id = project_map.get(normalize_value(project_name))
        if project_id is None:
            return f"System Info: project '{project_name}' does not exist."

        body, missing_entities = workpack_body_builder(payload, api_key)
    except LookupFailed as failure:
        return failure.system_info
    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist. {errors}."

    #In the commit_href returned by OP from /form the url doesn't contain an explicit link to the project, it needs to be setted manually
    body.setdefault('_links', {})['project'] = {"href": f"{API_V3}projects/{project_id}"}

    url = f"{API_V3}workspaces/{project_id}/work_packages"
    return {"method": "POST", "url": url, "body": body}


#function to construct the request for the UPDATE intent
def build_update_request(json_data, api_key) -> dict:
    if isinstance(json_data, dict) and 'properties' in json_data:
        json_data = json_data['properties']

    if not schema_validation(json_data):
        return "System Info: update failed, malformed extraction."

    #checks if macro_section is a valid possibility
    macro_section = json_data['macro_section']
    if macro_section == 'out_of_scope':
        return "System Info: operation not allowed, query out of domain."
    if macro_section not in ALLOWED_MACRO_SECTIONS:
        return "System Info: update is only supported for projects or work packages."

    selector = json_data['filters']
    payload = json_data['payload']
    if not payload:
        return "System Info: no fields provided to update"

    if macro_section == 'projects':
        try:
            project_id, error = validate_project_selector(selector, api_key)
        except LookupFailed as failure:
            return failure.system_info
        if error:
            return error
        get_url = f"{API_V3}projects/{project_id}"
        #return the method as a GET BUT specifies with the field 'patch_target' that needs also another request of type PATCH
        return {"method": "GET", "url": get_url,
                "patch_target": "project", "payload": payload}

    #macro_section is type work_packages and requires an id
    wp_id, error = validate_workpack_selector(selector)
    if error:
        return error
    get_url = f"{API_V3}work_packages/{wp_id}"

    return {"method": "GET", "url": get_url,
            "patch_target": "work_package", "payload": payload}


#function that does the actual request (it is only reached with a real url)
def fetch_openproject_data(final_url, api_key):
    try:
        response = requests.get(final_url, auth=('apikey', api_key))
        response.raise_for_status() #to check for example the case of invalid filter values
        data = response.json()

        #total only exists on a Collection
        if 'total' in data and data['total'] == 0:
            return "System Info: no result"

        return data

    except requests.exceptions.HTTPError:
        #the body of an error response is kept, behind the DEBUG flag, so it is there the next time without a code change
        debug_log("openproject error status", response.status_code)
        debug_log("openproject error headers", dict(response.headers))
        debug_log("openproject error body", response.text[:1000])

        return http_error_message(response.status_code)

    except Exception as e:
        return f"Error: {e}"

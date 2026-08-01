import json
import requests
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from llm_builder import build_llm
from structural_validation import normalize_value, schema_validation, resolve_date_filter, DATE_FIELDS
from request_helpers import (
    API_V3, api_key,
    create_ID_map, validate_project_selector, validate_workpack_selector,
    workpack_body_builder, project_body_builder,
    project_patch, workpack_patch,
    safe_write
)

#definition of the JSON structure that the LLM should return
class QueryParams(BaseModel):
    reasoning: str = Field(description="identify the intent, the macro-section, and the relevant filters/payload BEFORE answering.")
    intent: str = Field(description="Must be exactly 'read', 'create', or 'update'. Defaults to 'read' if the user is just asking a question.")
    macro_section: str = Field(description="Must be exactly 'projects' or 'work_packages', or 'out_of_scope' if out of scope.")
    filters: dict = Field(description="For 'read': the search parameters. For 'update': ONLY the selector of the target item (its 'id'). Empty for 'create'. IMPORTANT: every value inside this dictionary MUST be a list, even if there is only one element.",
                          examples=[{'priority': ['Low', 'High']}, {'active': ['t']}, {'assignee': ['Alba']}, {'dueDate': ['today']}])
    payload: dict = Field(default_factory=dict,
                          description="For 'create'/'update': the fields of the item to write. Empty ({}) for 'read'. IMPORTANT: every value inside this dictionary MUST be a list, even if there is only one element.",
                          examples=[{'subject': ['Login error'], 'priority': ['High'], 'dueDate': ['2026-09-15']}])

#structured template that uses the Chain of Thought
template = """You are an API semantic extractor.
Your ONLY task is to understand the user query and extract the intent, macro-section, and the search/write parameters.
DO NOT generate URLs. Output ONLY a valid JSON object matching the requested schema.

INTENT: Decide what the user wants to do
- 'read': the user is asking a question or looking something up. This is the DEFAULT.
- 'create': the user wants a NEW project or work package to be created.
- 'update': the user wants an EXISTING project or work package or a project to be modified (status, assignee, priority, ...).

ALLOWED MACRO-SECTIONS: 'projects' or 'work_packages'
CRITICAL SECTION DISAMBIGUATION: If the query asks for tasks, bugs, milestones, features, or priorities INSIDE a project, the macro-section is ALWAYS 'work_packages'.
Use 'projects' ONLY when searching for the projects themselves.

WHEN TO USE 'out_of_scope': a request is in scope ONLY if it reads, creates or updates projects or work packages using the fields listed below. Run these three checks; if ANY of them fails, set macro_section to 'out_of_scope', intent to 'read', and leave BOTH 'filters' and 'payload' empty ({{}}).
1. ENTITY: is it about projects or work packages? If it's not explicit than it's NOT.
2. ACTION: is it a read, a create or an update? Deleting, removing, copying, exporting or scheduling are NOT.
3. FIELD: is every field it mentions present in the lists below?
Naming a project or saying 'work package' does NOT put a request in scope: "Delete work package 15" fails check 2, "Show the custom fields of the work packages" fails check 1.

FILTERS vs PAYLOAD: They are never both non-empty
- For 'read': 'filters' holds the search parameters, 'payload' is an empty object {{}}.
- For 'create': 'filters' is an empty object {{}}, 'payload' holds the fields of the new item.
- For 'update': 'filters' holds ONLY the selector of the target item (its 'id'), 'payload' holds the fields to change.

ALLOWED FILTERS FOR 'projects':
- 'active': Use 't' or 'f' (If the project is currently active)
- 'public': Use 't' or 'f' (If the project is visible to everyone)
- 'name': Text to search in the project name
- 'id': Specific number ID of the project

ALLOWED FILTERS FOR 'work_packages':
- 'author': Name of the person who CREATED or OPENED the task. (CRITICAL: If the user says "created by X", it MUST be mapped to 'author', NEVER to 'assignee').
- 'assignee': Name of the person ASSIGNED to work on the task.
- 'priority': Priority level mentioned (e.g., 'Normal', 'Low', 'High', 'Immediate'), might be more than one
- 'status': The specific status or phase mentioned (e.g., 'Closed', 'New', 'Confirmed'). Extract the exact concept.
- 'id': Specific number ID of the task
- 'subject': Text to search in the title
- 'type': The type of work package (e.g., 'Milestone', 'Task', 'Bug', 'Feature'), use ALWAYS the singular
- 'version': The specific backlog, sprint, or phase it belongs to
- 'project': The name of the specific project these tasks belong to (e.g., 'Alpha', 'Data Migration')
- 'percentageDone': The completion percentage (e.g., '0', '50', '100') -- READ ONLY, see below
- 'startDate': The date the task should start (work packages only). See DATE VALUES below.
- 'dueDate': The deadline of the task (work packages only). See DATE VALUES below.

DATE VALUES (for 'startDate'/'dueDate' filters ONLY): use exactly one of these forms, never invent or calculate a date yourself:
- one explicit date -> one-element list, e.g. ["2026-09-15"]
- a date range -> two-element list [start, end], e.g. ["2026-09-01", "2026-09-30"]
- the keyword 'today' -> ["today"]
- the keyword 'this week' -> ["this week"]
Dates are always written as YYYY-MM-DD. If the user says "today" or "this week", output that exact keyword as the value, NOT a computed date.

WRITABLE FIELDS FOR 'payload' ON 'work_packages' (create/update ONLY): 'subject', 'description', 'startDate', 'dueDate', 'type', 'project', 'priority', 'status', 'version', 'assignee'.
- 'startDate'/'dueDate' in a payload are ALWAYS an explicit date "YYYY-MM-DD" — never 'today' or 'this week' (those are read-only keywords).
- 'author' and 'percentageDone' are NEVER writable: they must NEVER appear inside 'payload', under any circumstance. They can only be used inside 'filters' to search.

WRITABLE FIELDS FOR 'payload' ON 'projects' (create/update ONLY): 'name' (REQUIRED to create a project), 'active', 'public', 'description'.

CRITICAL RULE FOR MULTIPLE VALUES:
If the user asks for multiple values for the same filter (e.g., "Urgent tasks" might mean both "High" and "Immediate" priority), you MUST include all of them in a list.
ALL values in 'filters' and 'payload' MUST be formatted as lists (arrays), even if there is only one item.

EXAMPLE 1 (read):
User: "Find urgent milestones assigned to Alba in the Alpha project"
Output: {{"reasoning": "The user wants work packages. 'urgent' means priority High and Immediate. 'milestone' is the type. 'Alba' is the assignee. 'Alpha' is the project.", "intent": "read", "macro_section": "work_packages", "filters": {{"type": ["Milestone"], "priority": ["Immediate", "High"], "assignee": ["Alba"], "project": ["Alpha"]}}, "payload": {{}}}}

EXAMPLE 2 (create):
User: "Create a new bug in the Mobile App project, titled 'Login error', assign it to Mario Rossi with High priority, due September 15, 2026"
Output: {{"reasoning": "The user wants to create a new work package. Type is Bug, project is Mobile App, subject is 'Login error', assignee is Mario Rossi, priority is High, dueDate is an explicit date normalized to YYYY-MM-DD.", "intent": "create", "macro_section": "work_packages", "filters": {{}}, "payload": {{"project": ["Mobile App"], "type": ["Bug"], "subject": ["Login error"], "assignee": ["Mario Rossi"], "priority": ["High"], "dueDate": ["2026-09-15"]}}}}

EXAMPLE 3 (update):
User: "Mark task 321 as Closed"
Output: {{"reasoning": "The user wants to modify an existing work package identified by id 321, setting its status to Closed.", "intent": "update", "macro_section": "work_packages", "filters": {{"id": ["321"]}}, "payload": {{"status": ["Closed"]}}}}

EXAMPLE 4 (read, date keyword):
User: "Which work packages are due today?"
Output: {{"reasoning": "The user wants work packages whose dueDate is today. 'today' is a keyword resolved by the API, not a date to compute.", "intent": "read", "macro_section": "work_packages", "filters": {{"dueDate": ["today"]}}, "payload": {{}}}}

EXAMPLE 5 (out of scope):
User: "Delete work package 15"
Output: {{"reasoning": "It names a work package, but deleting is not one of the supported actions (read, create, update), so check 2 fails and the request is out of scope.", "intent": "read", "macro_section": "out_of_scope", "filters": {{}}, "payload": {{}}}}

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
def build_read_request(json_data) -> dict:
    if isinstance(json_data, dict) and 'properties' in json_data: #all the data are stored by default in the section properties of the json
        json_data = json_data['properties']

    if not schema_validation(json_data):
        return "System Info: query failed, data shape not valid"

    #checks if macro_section is a valid possibility
    macro_sect = json_data['macro_section']
    if macro_sect == 'out_of_scope':
        return 'Operation not allowed, query out of domain'
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
            dict_f = create_ID_map(key) #creates the dictionary only if it's needed

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

    if op_filters:
        json_string = json.dumps(op_filters)
        req = requests.Request('GET', base_url, params={"filters": json_string, 'sortBy':'[["createdAt","desc"]]'}) #to obtain the most recent results
        final_url = req.prepare().url
    else:
        final_url = base_url

    return {"method": "GET", "url": final_url}


#function to construct the request for the CREATE intent
def build_create_request(json_data) -> dict:
    if isinstance(json_data, dict) and 'properties' in json_data:
        json_data = json_data['properties']

    if not schema_validation(json_data):
        return "System Info: create failed, malformed extraction."

    #checks if macro_section is a valid possibility
    macro_section = json_data['macro_section']
    if macro_section == 'out_of_scope':
        return 'Operation not allowed, query out of domain'
    if macro_section not in ALLOWED_MACRO_SECTIONS:
        return "System Info: create is only supported for projects or work packages."

    payload = json_data['payload']
    if not payload:
        return "System Info: no fields provided to create the item."

    if macro_section == 'projects':
        body, missing_entities = project_body_builder(payload)
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
    project_map = create_ID_map('project')
    project_id = project_map.get(normalize_value(project_name))
    if project_id is None:
        return f"System Info: project '{project_name}' does not exist."

    body, missing_entities = workpack_body_builder(payload)
    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist. {errors}."

    url = f"{API_V3}workspaces/{project_id}/work_packages"
    return {"method": "POST", "url": url, "body": body}


#function to construct the request for the UPDATE intent
def build_update_request(json_data) -> dict:
    if isinstance(json_data, dict) and 'properties' in json_data:
        json_data = json_data['properties']

    if not schema_validation(json_data):
        return "System Info: update failed, malformed extraction."

    #checks if macro_section is a valid possibility
    macro_section = json_data['macro_section']
    if macro_section == 'out_of_scope':
        return 'Operation not allowed, query out of domain'
    if macro_section not in ALLOWED_MACRO_SECTIONS:
        return "System Info: update is only supported for projects or work packages."

    selector = json_data['filters']
    payload = json_data['payload']
    if not payload:
        return "System Info: no fields provided to update"

    if macro_section == 'projects':
        project_id, error = validate_project_selector(selector)
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
def fetch_openproject_data(final_url):
    try:
        response = requests.get(final_url, auth=('apikey', api_key))
        response.raise_for_status() #to check for example the case of invalid filter values
        data = response.json()

        if data.get('total', 0) == 0:
            return "System Info: no result"

        return data

    except requests.exceptions.HTTPError:
        if response.status_code == 400:
            return "System Info: invalid parameters or unsufficient permissions"
        else:
            return f"System Info: communication error, error: {response.status_code})."

    except Exception as e:
        return f"Error: {e}"

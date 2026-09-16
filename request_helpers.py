import os
import re
import requests
from dotenv import load_dotenv
from debug import debug_log
from structural_validation import normalize_value, DATE_FIELDS, ISO_DATE_RE

load_dotenv()
op_url = os.getenv('OP_URL')
#uses rstrip('/') because an OP_URL may end with a slash
API_V3 = op_url.rstrip('/') + '/api/v3/'

#one place deciding what each HTTP status means to the rest of the system
def http_error_message(status):
    """ the System Info that corresponds to an HTTP error status from OpenProject """
    if status == 400:
        #the request itself is malformed
        return "System Info: invalid parameters in the request."

    if status == 403:
        return "System Info: permission denied, OpenProject refused this request."

    if status == 404:
        return "System Info: the requested item does not exist."

    #everything else
    return f"System Info: communication error, error: {status}."


#used to name in the refusal the thing the user is not allowed to read
LOOKUP_LABEL = {
    'author': 'users', 'assignee': 'users', 'priority': 'priorities', 'status': 'statuses',
    'type': 'types', 'version': 'versions', 'project': 'projects',
}


class LookupFailed(Exception):
    def __init__(self, filter_name, status=None):
        self.filter_name = filter_name
        self.status = status
        super().__init__(f"{filter_name}: {status}")

    @property
    def system_info(self):
        label = LOOKUP_LABEL.get(self.filter_name, self.filter_name)
        if self.status in (401, 403):
            #same shape as every other refusal
            return ("System Info: permission denied, the current user is not allowed to "
                    f"look up {label}.")
        if self.status is None:
            return f"System Info: could not reach OpenProject to look up {label}."
        return http_error_message(self.status)


def validation_error_summary(errors):
    """ the readable part of OpenProject's validationErrors for the second model, which field is wrong and why.
    That information is what the second model needs in order to explain the problem to the user """
    if not isinstance(errors, dict) or not errors:
        return "the request is not valid"

    messages = []
    for field in sorted(errors):
        error = errors[field]
        text = error.get('message') if isinstance(error, dict) else None
        messages.append(text.strip().rstrip('.') if text else f"'{field}' is not acceptable")

    return "the request is not valid: " + "; ".join(messages)


#list of fields that need a mapping to create the href
LINK_FIELDS = {
    'assignee': 'users',
    'author': 'users',
    'priority': 'priorities',
    'status': 'statuses',
    'type': 'types',
    'version': 'versions',
}

#function to map the filter to the correct name
def build_get_ID_request(name):
    base_url = API_V3

    #builds the correct path based on the filter name
    if name == 'priority':
        base_url += 'priorities'

    elif name == 'author' or name == 'assignee':
        #principals, not users: /users is limited to administrators, while /principals returns the
        #people who are members of the projects the caller can see, which is the right scope anyway
        base_url += 'principals?pageSize=200'

    elif name == 'status':
        base_url += 'statuses'

    elif name == 'type':
        base_url += 'types'

    elif name == 'version':
        base_url += 'versions'

    elif name == 'project':
        base_url += 'projects'

    else:
        raise ValueError(f"Error, the filter '{name}' doesn't have an endpoint associated to an ID list.")
    return base_url


#function to create a dictionary with the real IDs of the specific filter
def create_ID_map(filter_name, api_key):
    #finds the correct URL
    url = build_get_ID_request(filter_name)

    #makes the request to get the json and creates a dictionary for that filter
    try:
        response = requests.get(url, auth=('apikey', api_key))
        response.raise_for_status() #in case of wrong URL (error 404)

        #transforms the json response into a python object to create the dictionary
        data = response.json()
        #with open(f"{filter_name}.json", "w") as file: #code to check the json obtained
        #    json.dump(data, file, indent=4)

        #every ID can be found inside a single element, which are under _embedded in the json
        elements = data.get('_embedded', {}).get('elements', [])

        #creates the dictionary with the name as key and the value as ID
        ID_dict = {}
        for el in elements:
            key = el.get('name')
            key = key.lower().strip()
            value = el.get('id')
            ID_dict[key] = value

        return ID_dict

    except requests.exceptions.HTTPError as err:
        status = err.response.status_code if err.response is not None else None
        debug_log(f"lookup of '{filter_name}' failed", status)
        raise LookupFailed(filter_name, status) from err

    except Exception as e:
        #network failure, timeout, malformed answer: we did not find out, which is not the same as
        #"the entity does not exist"
        debug_log(f"lookup of '{filter_name}' failed", e)
        raise LookupFailed(filter_name) from e


#an extension of create_ID_map, specific to resolve the project selector for the intent 'update'
def validate_project_selector(selector, api_key):
    """ project can be found by id or by a name (fetching the corrisponding ID)"""
    #the user provided an ID
    if selector.get('id'):
        return selector['id'][0], None

    #the user provided a name
    if selector.get('name'):
        name = selector['name'][0]

        project_map = create_ID_map('project', api_key)
        project_id = project_map.get(normalize_value(name))

        if project_id is None:
            return None, f"System Info: project '{name}' does not exist."
        return project_id, None

    return None, "System Info: update currently requires a project 'id' or 'name' selector."

def validate_workpack_selector(selector):
    """ checks if the user provided a valid ID to find the corrisponding work package """
    if not selector.get('id'):
        return None, "System Info: update currently requires an explicit work package id."

    return selector['id'][0], None


#functions to write the body of the request (create or update)
def workpack_body_builder(payload, api_key, for_update=False):
    """ for_update tells the builder WHERE the project has to go """
    body = {}
    links = {}
    missing_entities = []

    for key, val_list in payload.items():
        if key == 'project':
            if not for_update:
                #the URL already carries the project: POST /workspaces/{id}/work_packages
                continue
            if not val_list:
                missing_entities.append("'project' has no value")
                continue
            project_map = create_ID_map('project', api_key)
            project_id = project_map.get(normalize_value(val_list[0]))
            if project_id is None:
                missing_entities.append(f"'value: {val_list[0]}' for the parameter project")
            else:
                links['project'] = {"href": f"{API_V3}projects/{project_id}"}
            continue

        #the schema guarantees a list, but not that it has a value inside
        if not val_list:
            missing_entities.append(f"'{key}' has no value")
            continue

        value = val_list[0]

        #author and percentageDone are not writable, only readable
        if key in ('author', 'percentageDone'):
            missing_entities.append(f"'{key}' is not a writable field")
            continue

        #startDate/dueDate go in the root as "YYYY-MM-DD", always explicit (never 'today'/'this week')
        if key in DATE_FIELDS:
            clean_date = str(value).strip()
            if not ISO_DATE_RE.match(clean_date):
                missing_entities.append(f"'{key}': '{value}' is not a valid YYYY-MM-DD date")
            else:
                body[key] = clean_date
            continue

        #some fields need an href with the corrisponding ID, that means they need to be mapped
        if key in LINK_FIELDS:
            id_map = create_ID_map(key, api_key)
            entity_id = id_map.get(normalize_value(value))
            if entity_id is None:
                missing_entities.append(f"'value: {value}' for the parameter {key}")
                continue
            links[key] = {"href": f"{API_V3}{LINK_FIELDS[key]}/{entity_id}"}

        elif key == 'description':
            body['description'] = {"format": "markdown", "raw": str(value)}

        elif key == 'subject':
            body['subject'] = str(value)

        else:
            #unknown field or field not supported in this project
            missing_entities.append(f"unrecognized field '{key}'")

    if links:
        body['_links'] = links

    return body, missing_entities


def project_body_builder(payload):
    body = {}
    missing_entities = []

    for key, val_list in payload.items():
        #the schema guarantees a list, but not that it has a value inside
        if not val_list:
            missing_entities.append(f"'{key}' has no value")
            continue

        value = val_list[0]

        if key in ('active', 'public'):
            body[key] = normalize_value(value) in ('t', 'true', '1')

        elif key == 'name':
            body['name'] = str(value)

        elif key == 'description':
            body['description'] = {"format": "markdown", "raw": str(value)}
            
        else:
            #unknown field or field not supported in this project
            missing_entities.append(f"unrecognized field '{key}'")

    return body, missing_entities


#functions to patch project and workpackages for an update request
def project_patch(get_response, payload, get_url, api_key):
    if not isinstance(get_response, dict):
        return "System Info: could not read the current project to update."

    body, missing_entities = project_body_builder(payload)
    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist. {errors}."

    return {"method": "PATCH", "url": get_url, "body": body}

def workpack_patch(get_response, payload, get_url, api_key):
    #the update of a workpackage needs a lockVersion obtained with the GET (read) request
    if not isinstance(get_response, dict) or 'lockVersion' not in get_response:
        return "System Info: could not read the current work package to update."

    try:
        body, missing_entities = workpack_body_builder(payload, api_key, for_update=True)
    except LookupFailed as failure:
        return failure.system_info

    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist. {errors}."

    body['lockVersion'] = get_response['lockVersion']
    project_href = get_response.get('_links', {}).get('project', {}).get('href')

    return {"method": "PATCH", "url": get_url, "body": body, "project": project_href}


def validate_via_form(request, api_key):
    """ does a request without executing the real action (update/write), just checks that everything is correct and safe (permissions) """
    if "url" not in request or "body" not in request:
        return "System Info: nothing to validate, malformed write request."

    form_url = request["url"].rstrip("/") + "/form"

    try:
        response = requests.post(form_url, json=request["body"], auth=('apikey', api_key))
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as err:
        #every HTTP status goes through the single mapping in http_error_message(), the same one used for reads
        status = err.response.status_code if err.response is not None else None
        try:
            debug_log("form validation error body", err.response.json())
        except Exception:
            debug_log("form validation error body (not json)",
                      err.response.text[:1000] if err.response is not None else None)
        return http_error_message(status)
    except Exception as e:
        return f"System Info: could not reach OpenProject to validate, error: {e}."

    errors = data.get("_embedded", {}).get("validationErrors", {})
    commit_link = data.get("_links", {}).get("commit")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "can_commit": commit_link is not None, #field commit is not empty only if the request went well
        "commit_href": commit_link.get("href") if commit_link else None,
        "commit_method": (commit_link.get("method") if commit_link else None) or "post",
    }


def safe_write(request, api_key):
    """ defines if the request is valid or not and communicate the permission to execute the real query """
    if isinstance(request, str):
        return request

    validation = validate_via_form(request, api_key)
    if isinstance(validation, str):
        return validation

    if not validation["valid"]:
        #the raw structure stays in the log, the readable summary goes to the answer
        debug_log("form validation errors", validation["errors"])
        return f"System Info: {validation_error_summary(validation['errors'])}."

    if not validation["can_commit"]:
        return "System Info: the request is valid but cannot be committed right now."


    return {
        **request,
        "ready_to_commit": True,
        "commit_href": validation["commit_href"],
        "commit_method": validation["commit_method"],
    }


def commit_write(validated_request, api_key):
    """ executes a write that was already validated by safe_write(), that is if ready_to_commit is set as True.
   Uses the commit_href/commit_method returned from /form by OP """
    if not isinstance(validated_request, dict) or not validated_request.get("ready_to_commit"):
        return "System Info: nothing to commit, the request was not validated as ready."

    commit_href = validated_request.get("commit_href")
    if not commit_href:
        return "System Info: no commit link available, cannot execute the write."

    commit_url = commit_href if commit_href.startswith("http") else op_url.rstrip("/") + commit_href
    method = (validated_request.get("commit_method") or "post").lower()
    body = validated_request.get("body", {})

    try:
        response = requests.request(method, commit_url, json=body, auth=('apikey', api_key))
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as err:
        status = err.response.status_code if err.response is not None else None
        try:
            debug_log("commit error body", err.response.json())
        except Exception:
            debug_log("commit error body (not json)",
                      err.response.text[:1000] if err.response is not None else None)
        return http_error_message(status)

    except Exception as e:
        return f"System Info: could not reach OpenProject to commit, error: {e}."
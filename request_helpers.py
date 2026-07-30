import os
import re
import requests
from dotenv import load_dotenv
from structural_validation import normalize_value

load_dotenv()
api_key = os.getenv('OP_API_KEY')
op_url = os.getenv('OP_URL')
API_V3 = op_url + '/api/v3/'

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
        base_url += 'users'

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
def create_ID_map(filter_name):
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

    except Exception as e:
        print(f'Error while retrieving the filter {filter_name}', e)
        return {}


#an extension of create_ID_map, specific to resolve the project selector for the intent 'update'
def validate_project_selector(selector):
    """ project can be found by id or by a name (fetching the corrisponding ID)"""
    if not isinstance(selector, dict):
        selector = {}

    #the user provided an ID
    if 'id' in selector:
        val = selector['id']
        return val[0], None

    #the user provided a name
    if 'name' in selector:
        val = selector['name']
        val = val[0]

        #finds the corrisponding ID (if the project exists)
        project_map = create_ID_map('project')
        project_id = project_map.get(normalize_value(val))
        if project_id is None:
            return None, f"System Info: project '{val}' does not exist."
        return project_id, None

    return None, "System Info: update currently requires a project 'id' or 'name' selector."

def validate_workpack_selector(selector, entity_label):
    """ checks if the user provided a valid ID to find the corrisponding work package """
    if not isinstance(selector, dict) or 'id' not in selector:
        return None, f"System Info: update currently requires an explicit {entity_label} id."

    val = selector['id']
    return (val[0] if isinstance(val, list) else val), None


#functions to write the body of the request (create or update)
def workpack_body_builder(payload):
    body = {}
    links = {}
    missing_entities = []

    for key, val_list in payload.items():
        #the url request has the project in the url, there's no need to write it in the body
        if key == 'project':
            continue

        value = val_list[0]

        #some fields need an href with the corrisponding ID, that means they need to be mapped
        if key in LINK_FIELDS:
            id_map = create_ID_map(key)
            entity_id = id_map.get(normalize_value(value))
            if entity_id is None:
                missing_entities.append(f"'value: {value}' for the parameter {key}")
                continue
            links[key] = {"href": f"{API_V3}{LINK_FIELDS[key]}/{entity_id}"}

        elif key == 'description':
            body['description'] = {"format": "markdown", "raw": str(value)}

        elif key == 'percentageDone':
            try:
                body['percentageDone'] = int(value)
            except (TypeError, ValueError):
                missing_entities.append(f"'value: {value}' is not a valid percentageDone")

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
        value = val_list[0]

        if key in ('active', 'public'):
            body[key] = normalize_value(value) in ('t', 'true', '1')
        elif key == 'name':
            body['name'] = str(value)
        else:
            #unknown field or field not supported in this project
            missing_entities.append(f"unrecognized field '{key}'")

    return body, missing_entities


#functions to patch project and workpackages for an update request
def project_patch(get_response, payload, get_url):
    if not isinstance(get_response, dict):
        return "System Info: could not read the current project to update."

    body, missing_entities = project_body_builder(payload)
    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist. {errors}."

    return {"method": "PATCH", "url": get_url, "body": body}

def workpack_patch(get_response, payload, get_url):
    #the update of a workpackage needs a lockVersion obtained with the GET (read) request
    if not isinstance(get_response, dict) or 'lockVersion' not in get_response:
        return "System Info: could not read the current work package to update."

    body, missing_entities = workpack_body_builder(payload)
    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist. {errors}."

    body['lockVersion'] = get_response['lockVersion']
    project_href = get_response.get('_links', {}).get('project', {}).get('href')

    return {"method": "PATCH", "url": get_url, "body": body, "project": project_href}


def validate_via_form(request):
    """ does a request without executing the real action (update/write), just checks that everything is correct and safe (permissions) """
    if not isinstance(request, dict) or "url" not in request or "body" not in request:
        return "System Info: nothing to validate, malformed write request."

    form_url = request["url"].rstrip("/") + "/form"

    try:
        response = requests.post(form_url, json=request["body"], auth=('apikey', api_key))
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as err:
        status = err.response.status_code if err.response is not None else None
        try:
            data = err.response.json()
        except Exception:
            return f"System Info: form validation call failed, error {status}."

        #specific code returned by Form meaning the request cannot be resolved because of lacking permissions
        if status == 403:
            return f"System Info: permission denied, {data.get('message', 'you are not allowed to perform this action.')}"

        return f"System Info: form validation call failed, error {status}: {data.get('message', data)}."
    except Exception as e:
        return f"System Info: could not reach OpenProject to validate, error: {e}."

    errors = data.get("_embedded", {}).get("validationErrors", {})
    commit_link = data.get("_links", {}).get("commit")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "can_commit": commit_link is not None, #field commit is not empty only if the request went well
        "commit_href": commit_link.get("href") if commit_link else None,
    }


def safe_write(request):
    """ defines if the request is valid or not and communicate the permission to execute the real query """
    if isinstance(request, str):
        return request

    validation = validate_via_form(request)
    if isinstance(validation, str):
        return validation

    if not validation["valid"]:
        return f"System Info: the request is not valid, {validation['errors']}."

    if not validation["can_commit"]:
        return "System Info: the request is valid but cannot be committed right now."

    return {**request, "ready_to_commit": True}
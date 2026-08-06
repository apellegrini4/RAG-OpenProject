from fastapi import FastAPI
from pydantic import BaseModel
import json
from structured_URL_generator import (
parser, define_urlConstructor_chain, fetch_openproject_data,
    build_read_request, build_create_request, build_update_request, safe_write,
    project_patch, workpack_patch,
)
from response_generator import define_response_chain
from json_pruning import clean_and_remodel_json

import time

app = FastAPI()

class requestStructure(BaseModel):
    username: str
    question: str
    model_name: str


def intent_identifier(json_data):
    """ builds the right request based on the intent extracted by the model. The schema's default intent is read """
    intent = json_data.get('intent') if isinstance(json_data, dict) else None

    if intent == 'read' or intent is None:
        return build_read_request(json_data)
    if intent == 'create':
        return build_create_request(json_data)
    if intent == 'update':
        return build_update_request(json_data)

    return f"System Info: unknown intent '{intent}'"


def execute(json_data):
    """ identifies the intent and excecute it"""
    request = intent_identifier(json_data)

    #if it's a string it means that it's a System Info
    if isinstance(request, str):
        return request

    #a patch_target means the intent is an update (read then write, the PATCH needs the lockVersion)
    if "patch_target" in request:
        get_response = fetch_openproject_data(request["url"])
        patch_function = project_patch if request["patch_target"] == "project" else workpack_patch
        patch_request = patch_function(get_response, request["payload"], request["url"])
        return safe_write(patch_request)

    #a GET without a patch_target is a read
    if request["method"] == "GET":
        data = fetch_openproject_data(request["url"])
        return clean_and_remodel_json(data)

    #the intent is a creation (a simple write)
    return safe_write(request)


@app.post("/ask")
async def ask_agent(request: requestStructure):
    start_time = time.time() #saves the time at the beginning of the request

    try:
        #creation of the chains for the 2 models
        url_constructur_chain = define_urlConstructor_chain(request.model_name)
        response_chain = define_response_chain(request.model_name)

        json_params = url_constructur_chain.invoke({"format_instructions": parser.get_format_instructions(),
                                    "user_query": request.question})
        
        with open("tests/stress_test.json", "r") as f:
            final_data = json.load(f)
        # final_data = execute(json_params)

        #a read returns a dictionary, a failure returns a plain "System Info" string
        if isinstance(final_data, dict):
            total = final_data.get('total_results', 0)
            page = final_data.get('number_of_results_in_the_page', 0)

            if total > page:
                final_data['pagination_warning'] = f"I found {total} results but I'm only showing you the {page} recent ones."

            json_data = json.dumps(final_data, indent=2)
        else:
            json_data = str(final_data)

        response = response_chain.invoke({'json' : json_data,
          'user_query' : request.question 
        })

        execution_time = round(time.time() - start_time, 2) #calcutes the response generation time

        return {
            "model_choosen": request.model_name,
            "execution_time": execution_time,
            "answer": response
        }

    except Exception as e:
        return f"System Info: the request could not be completed, error: {e}"
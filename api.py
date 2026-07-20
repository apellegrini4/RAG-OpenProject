from fastapi import FastAPI
from pydantic import BaseModel
import json
from structured_URL_generator import parser, build_OP_URL, define_urlConstructor_chain, fetch_openproject_data
from response_generator import define_response_chain
from json_pruning import clean_and_remodel_json

import time

app = FastAPI()

class requestStructure(BaseModel):
    username: str
    question: str
    model_name: str

@app.post("/ask")
async def ask_agent(request: requestStructure):
    start_time = time.time() #saves the time at the beginning of the request

    try:
        #creation of the chains for the 2 models
        url_constructur_chain = define_urlConstructor_chain(request.model_name)
        response_chain = define_response_chain(request.model_name)

        user_query = f"{request.question} (Note: the user asking is {request.username})"

        json_params = url_constructur_chain.invoke({"format_instructions": parser.get_format_instructions(),
                                    "user_query": user_query})
        
        url = build_OP_URL(json_params)

        with open("tests/stress_test.json", "r") as f:
            final_data = json.load(f)
        # data = fetch_openproject_data(url)
        # final_data = clean_and_remodel_json(data)

        if isinstance(final_data, dict): #check to see if there are data, in fact it may also be a string with the error
            total = final_data.get('total_results', 0)
            page = final_data.get('number_of_results_in_the_page', 0)
            if total > page: final_data['pagination_warning'] = f"I found {total} results but I'm only showing you the {page} recent ones."

        if isinstance(final_data, dict) or isinstance(final_data, list):
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
        return e
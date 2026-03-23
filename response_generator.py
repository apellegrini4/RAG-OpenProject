import json
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOllama(model='mistral', temperature=0.5)
parser = StrOutputParser()

#I don't need the generation of 5 different queries anymore
template = '''You are a professional AI language model assistant. 
    Your task is to answer the user's query using ONLY the context you extract by the JSON that's given to you.

    RULES:
    - You need to answer in a natural language and you CANNOT invent or hallucinate information. If you can't find the answer inside of the json you need to responde politly that you don't have that information.
    - You NEED to COMPARE the section: total_results with the other section: number_of_results_in_the_page. If the first one is GREATER than the other one you MUST INFORM the user that you are only showing the most recent results.
    - If the json contains an 'error' or a 'System Info' communicate and explain the problem politly to the user.
    - DO NOT deduce, interpret or translate the exact values in the JSON, your job is only to report the data you find.

    {json}

    USER QUERY: {user_query}
'''


prompt = ChatPromptTemplate.from_template(template)
chain = (   prompt 
        |   llm 
        |   parser 
)

def generate_response(user_query, reduced_json):
    if isinstance(reduced_json, dict) or isinstance(reduced_json, list):
        json_data = json.dumps(reduced_json, indent=2)
    else:
        json_data = str(reduced_json)

    try:
        response = chain.invoke({
          'json' : json_data,
          'user_query' : user_query  
        })

        return response
    
    except Exception as e:
        return 'I am sorry, there was an error in the generation of the response'


#--------------------
#TEMPORARY TEST
if __name__ == "__main__":
    #example
    mock_pruned_json = {
        "total_results": 3,
        "number_of_results_in_the_page": 3,
        "items": [
            {
                "type_entity": "WorkPackage",
                "id": 37,
                "subject": "task1",
                "createdAt": "2026-03-13T10:55:08.576Z",
                "type": "Bug",
                "status": "Confirmed",
                "priority": "High",
                "project": "E-commerce Redesign",
                "assignee": "Alba Pellegrini"
            },

            {
                "type_entity": "WorkPackage",
                "id": 42,
                "subject": "task7",
                "createdAt": "2026-03-13T10:55:08.576Z",
                "type": "Bug",
                "status": "Developed",
                "priority": "Low",
                "project": "E-commerce Redesign",
                "assignee": "Alba Pellegrini"
            },

            {
                "type_entity": "WorkPackage",
                "id": 73,
                "subject": "task9",
                "createdAt": "2026-03-13T10:55:08.576Z",
                "type": "Bug",
                "status": "Test failed",
                "priority": "Medium",
                "project": "E-commerce Redesign",
                "assignee": "Alba Pellegrini"
            }
        ]
    }
    
    question = "Show me all open bug assigned to Alba Pellegrini in the project E-commerce Redesign. Than explain your tought process"
    
    print("Processing response...\n")
    final_response = generate_response(question, mock_pruned_json)
    
    print("--- RESPONSE ---")
    print(final_response)
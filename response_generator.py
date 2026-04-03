import json
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOllama(model='mistral', temperature=0.5) #changed the model from mistral to llama3.1
parser = StrOutputParser()

#I don't need the generation of 5 different queries anymore
template = '''You are a professional AI language model assistant. 
    Your task is to answer the user's query using ONLY the context you extract by the JSON that's given to you.

    RULES:
    - You need to answer in a natural language and you CANNOT invent or hallucinate information. If you can't find the answer inside of the json you need to responde politly that you don't have that information.
    - You NEED to COMPARE the section: total_results with the other section: number_of_results_in_the_page. ONLY if the first one is GREATER than the other one you MUST INFORM the user that you are only showing the most recent results, OTHERWISE DON'T MENTION the comparison.
    - If the json contains an 'error' or a 'System Info' your ONLY job is to report the exact error reason to the user and suggest they verify their permissions. DO NOT invent or mention any tasks.
    - DO NOT deduce, interpret or translate the exact values in the JSON, your job is only to report the data you find.
    - The conversation MUST be natural, NEVER mention the words 'json' or 'data provided'. If there is one task, instead of reffering to the json, say for example: 'I found one open task'.
    - Always provide the details of the items you find. List the ID, Subject/Title, and Status of the items so the user knows exactly what they are.

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
#if __name__ == "__main__":
#    #example
#    mock_pruned_json = {
#        "total_results": 3,
#        "number_of_results_in_the_page": 3,
#        "items": [
#            {
#                "type_entity": "WorkPackage",
#                "id": 37,
#                "subject": "task1",
#                "createdAt": "2026-03-13T10:55:08.576Z",
#                "type": "Bug",
#                "status": "Confirmed",
#                "priority": "High",
#                "project": "E-commerce Redesign",
#                "assignee": "Alba Pellegrini"
#            },
#
#            {
#                "type_entity": "WorkPackage",
#                "id": 42,
#                "subject": "task7",
#                "createdAt": "2026-03-13T10:55:08.576Z",
#                "type": "Bug",
#                "status": "Developed",
#                "priority": "Low",
#                "project": "E-commerce Redesign",
#                "assignee": "Alba Pellegrini"
#            },
#
#            {
#                "type_entity": "WorkPackage",
#                "id": 73,
#                "subject": "task9",
#                "createdAt": "2026-03-13T10:55:08.576Z",
#                "type": "Bug",
#                "status": "Test failed",
#                "priority": "Medium",
#                "project": "E-commerce Redesign",
#                "assignee": "Alba Pellegrini"
#            }
#        ]
#    }
#    
#    question = "Show me all open bug assigned to Alba Pellegrini in the project E-commerce Redesign."
#    
#    print("Processing response...\n")
#    final_response = generate_response(question, mock_pruned_json)
#    
#    print("--- RESPONSE ---")
#    print(final_response)
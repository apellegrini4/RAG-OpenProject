import json
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

#I don't need the generation of 5 different queries anymore
template = '''You are a professional AI language model assistant. 
    Your task is to answer the user's query using ONLY the context you extract by the JSON that's given to you.

    RULES:
    - You need to answer in a natural language and you CANNOT invent or hallucinate information. If you can't find the answer inside of the json you need to responde politly that you don't have that information.
    - If the context contains a 'pagination_warning' you MUST include the exact warning inat the end of your response.
    - If the context contains 'System Info' or any error message, output a SINGLE, brief, and natural sentence. Explain that the search failed due to that specific error and suggest checking the project status. Your entire response must be exactly one concise sentence explaining the issue.
    - Always provide the details of the items you find. List the ID, Subject/Title, and Status of the items so the user knows exactly what they are.
    - DO NOT deduce, interpret or translate the exact values in the JSON, your job is only to report the data you find.
    - The conversation MUST be natural, NEVER mention the words 'json' or 'data provided'. If there is one task, instead of reffering to the json, say for example: 'I found one open task'.
    - NEVER append notes, P.S., or explanations about your internal process.

    {json}

    USER QUERY: {user_query}
'''
    # - You NEED to COMPARE the section: total_results with the other section: number_of_results_in_the_page. ONLY if the first one is GREATER than the other one you MUST INFORM the user that you are only showing the most recent results, OTHERWISE DON'T MENTION the comparison.

#setting of the parser and creation of the chain
parser = StrOutputParser()
prompt = ChatPromptTemplate.from_template(template)

def define_response_chain(model_name):
    llm = ChatOllama(model=model_name, temperature=0)
    chain = (   prompt 
            |   llm 
            |   parser 
    )

    return chain


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
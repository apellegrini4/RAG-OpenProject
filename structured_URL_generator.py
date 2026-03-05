import os
import json
import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

#definizione della struttura JSON che deve restituire l'LLM
class QueryParams(BaseModel):
    #aggiunta del chain of thought
    reasinoning: str = Field(description="think")
    macro_section: str = Field(description="Must be exactly 'projects' or 'work_packages', or 'not_allowed' if out of scope.")
    filters: dict = Field(description="Dictionary of extracted parameters. IMPORTANT: Every value inside this dictionary MUST be a list, even if there is only one element.",
                          examples=[{'priority': ['Low', 'High']}, {'active': ['t']}, {'assignee': ['Alba']}] )

#scelta del modello e del parser
llm = ChatOllama(model='llama3.1', temperature=0, format="json")
parser = JsonOutputParser(pydantic_object=QueryParams)

#scrittura di un template strutturato che sfrutti anche il Chain of Thought
template = """You are an API semantic extractor.
Your ONLY task is to understand the user query and extract the macro-section and the search parameters.
DO NOT generate URLs. Output ONLY a valid JSON object matching the requested schema.

ALLOWED MACRO-SECTIONS: 'projects' or 'work_packages'
CRITICAL SECTION DISAMBIGUATION: If the query asks for tasks, bugs, milestones, features, or priorities INSIDE a project, the macro-section is ALWAYS 'work_packages'.
Use 'projects' ONLY when searching for the projects themselves.
IF the macro-section that you find is NOT allowed USE 'not_allowed'.

ALLOWED FILTERS FOR 'projects':
- 'active': Use 't' or 'f' (If the project is currently active)
- 'public': Use 't' or 'f' (If the project is visible to everyone)
- 'name': Text to search in the project name
- 'id': Specific number ID of the project

ALLOWED FILTERS FOR 'work_packages':
- 'author': Name of the person who CREATED or OPENED the task. (CRITICAL: If the user says "created by X", it MUST be mapped to 'author', NEVER to 'assignee').
- 'assignee': Name of the person ASSIGNED to work on the task.
- 'priority': Priority level mentioned (e.g., 'Normal', 'Low', 'High', 'Immediate'), might be more than one
- 'status': The specific status or phase mentioned (e.g., 'Open', 'Closed', 'New', 'Confirmed'). Extract the exact concept.
- 'id': Specific number ID of the task
- 'subject': Text to search in the title
- 'type': The type of work package (e.g., 'Milestone', 'Task', 'Bug', 'Feature')
- 'version': The specific backlog, sprint, or phase it belongs to
- 'project': The name of the specific project these tasks belong to (e.g., 'Alpha', 'Data Migration')
- 'percentageDone': The completion percentage (e.g., '0', '50', '100')

CRITICAL RULE FOR MULTIPLE VALUES:
If the user asks for multiple values for the same filter (e.g., "Urgent tasks" might mean both "High" and "Immediate" priority), you MUST include all of them in a list. 
Actually, ALL values in the filters dictionary MUST be formatted as lists (arrays), even if there is only one item.

EXAMPLE:
User: "Find urgent milestones assigned to Alba in the Alpha project"
Output: {{"reasoning": "The user wants work packages. 'urgent' means priority High and Immediate. 'milestones' is the type. 'Alba' is the assignee. 'Alpha' is the project.", "macro_section": "work_packages", "filters": {{"type": ["Milestones"], "priority": ["Immediate", "High"], "assignee": ["Alba"], "project": ["Alpha"]}}}}

{format_instructions}

User query: {user_query}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | llm | parser

#TEST SECTION
#first test set
#test_queries = [
#    "Show me all active and public projects.",
#    "Search for the project named Data Migration.",
#
#    "Find the tasks assigned to Mario Rossi.",
#    "What are the open bugs?",
#
#    "Find the urgent milestones or features in the Alpha project.",
#    "Show me the tasks created by Alba that are 100'%' completed.",
#
#    "Give me the list of all registered users in the system.",
#    "Search for the work package with ID 42."
#]
#
##new test set to verify the model ability to understand and adapt
blind_test_queries = [
    "Show me the closed features in the Beta project that were created by Alba and assigned to Mario.",
    
    "I need to see the work package number 99.",
    
    "What is the total financial budget for the Data Migration project?",
    
    #OR condition, not possible to do it in OpenProject (TO DO: decide if u wanna keep it or not as exemple)
    "Find tasks assigned to Alba that are either urgent or 50% completed."
]

risultato = []
for i, q in enumerate(blind_test_queries):
    print(f"query {i+1}: ", {q})
    try:
        risultato.append(chain.invoke({"format_instructions": parser.get_format_instructions(), "user_query": q}))
        #print(risultato)
        #print(40*'-')
    except Exception as e:
        print('errore: ', e)


load_dotenv()
api_key = os.getenv('OP_API_KEY')
op_url = os.getenv('OP_URL')
API_V3_BASE = op_url + '/api/v3/'

def build_get_ID_request(name):
    base_url = API_V3_BASE

    #builds the correct path for the get based on the filter name
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
        raise ValueError(f"Errore: Il filtro '{name}' non ha un endpoint associato per gli ID.")
    return base_url

def create_ID_map(filter_name):
    #finds the correct URL
    url = build_get_ID_request(filter_name)

    #makes the request to get the json and creates a dictionary for that filter
    try:
        response = requests.get(url, auth=('apikey', api_key))
        response.raise_for_status() #in case of wrong URL (error 404) --> in the future it can be changed by considering the number of the error, because some users might receive error 402 (?) if they lack of permissions

        #transforms the response into a json to create the dictionary
        data = response.json()

        #every ID can be found inside a single element, which are under _embedded in the json
        elements = data.get('_embedded', {}).get('elements', {})

        #creates the dictionary with the name as key and the value as ID
        ID_dict = {}
        for el in elements:
            key = el.get('name')
            value = el.get('id')
            ID_dict[key] = value

        return ID_dict

    except Exception as e:
        print(f'Error while retrieving the filter {filter_name}')
        return {}

def build_OP_URL(json):
    #manages the 'not_allowed' case
    if json['macro_section'] == 'not_allowed':
        return 'Operation not allowed, query out of domain'

    macro_sect = json['macro_section']
    #if the macro-section is valid creates the first part of the request
    base_url = API_V3_BASE
    base_url += f'{macro_sect}'
    print(base_url)
    
    #we extract the filters
    filters = json.get('filters', {})
    print(filters)

    #creates a dictionary only if the filter needs it

    return ...

build_OP_URL(risultato[0])

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
    reasoning: str = Field(description="think")
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
- 'status': The specific status or phase mentioned (e.g., 'Closed', 'New', 'Confirmed'). Extract the exact concept.
- 'id': Specific number ID of the task
- 'subject': Text to search in the title
- 'type': The type of work package (e.g., 'Milestone', 'Task', 'Bug', 'Feature'), use ALWAYS the singular
- 'version': The specific backlog, sprint, or phase it belongs to
- 'project': The name of the specific project these tasks belong to (e.g., 'Alpha', 'Data Migration')
- 'percentageDone': The completion percentage (e.g., '0', '50', '100')

CRITICAL RULE FOR MULTIPLE VALUES:
If the user asks for multiple values for the same filter (e.g., "Urgent tasks" might mean both "High" and "Immediate" priority), you MUST include all of them in a list. 
Actually, ALL values in the filters dictionary MUST be formatted as lists (arrays), even if there is only one item.

EXAMPLE:
User: "Find urgent milestones assigned to Alba in the Alpha project"
Output: {{"reasoning": "The user wants work packages. 'urgent' means priority High and Immediate. 'milestone' is the type. 'Alba' is the assignee. 'Alpha' is the project.", "macro_section": "work_packages", "filters": {{"type": ["Milestone"], "priority": ["Immediate", "High"], "assignee": ["Alba"], "project": ["Alpha"]}}}}

{format_instructions}

User query: {user_query}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | llm | parser

#QUERIES SECTION
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

#new test set queries
second_test_set_queries = [
    # 1. Stress Test Multi-Filtro (Mappa status, type, assignee, project)
    "Show me all open bug assigned to Alba Pellegrini in the project E-commerce Redesign.",
    
    # 2. Ricerca Testuale mista (Mappa subject, project)
    "Search for task that containes the word 'database' in the title inside the project E-commerce Redesign.",
    
    # 3. Disambiguazione Autore (Invece di usare due persone, cerchiamo solo per autore)
    "Show me the tasks created by Alba Pellegrini which have High priority.",
    
    # 4. Ricerca Base sui Progetti
    "Give me the list of all active and public projects.",
    
    # 5. Condizione incrociata senza progetto o utente
    "What are the closed features with normal priority."
]


load_dotenv()
api_key = os.getenv('OP_API_KEY')
op_url = os.getenv('OP_URL')
API_V3 = op_url + '/api/v3/'

#FUNCTIONS SECTION
#function to map the filter to the correct name
def build_get_ID_request(name):
    base_url = API_V3

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
        raise ValueError(f"Error, the filter '{name}' does'nt have an endpoint associated to an ID list.")
    return base_url

#function to create a dictionary with the real ID's of the specific filter
def create_ID_map(filter_name):
    #finds the correct URL
    url = build_get_ID_request(filter_name)

    #makes the request to get the json and creates a dictionary for that filter
    try:
        response = requests.get(url, auth=('apikey', api_key))
        response.raise_for_status() #in case of wrong URL (error 404) --> in the future it can be changed by considering the number of the error, because some users might receive error 402 (?) if they lack of permissions

        #transforms the response into a json to create the dictionary
        data = response.json()
        #with open(f"{filter_name}.json", "w") as file: #code to check the json obtained
        #    json.dump(data, file, indent=4)

        #every ID can be found inside a single element, which are under _embedded in the json
        elements = data.get('_embedded', {}).get('elements', {})

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

#function to construct the final URL
def build_OP_URL(json_data):
    if isinstance(json_data, dict) and 'properties' in json_data: #all the data are stored by default in the section properties of the json
        json_data = json_data['properties']

    if not isinstance(json_data, dict) or 'macro_section' not in json_data:
            return "System Info: query failed."

    #manages the 'not_allowed' case
    if json_data['macro_section'] == 'not_allowed':
        return 'Operation not allowed, query out of domain'

    macro_sect = json_data['macro_section']
    #if the macro-section is valid creates the first part of the request
    base_url = API_V3
    base_url += f'{macro_sect}'
    
    #we extract the filters
    filters = json_data.get('filters', {})
    #print('filters extracted \n', filters)

    #creates a dictionary only if the filter needs it
    f_need_map = ['author', 'assignee', 'priority', 'status', 'type', 'version', 'project']

    op_filters = []
    missing_entities = []

    for key, val_list in filters.items():
        mapped_values = []
        operator = '='
        op_key = key #the name of the filter to put in the query

        #rule for open and closed statuses, it manages the case and then goes on with the next filter
        if key == 'status':
            is_open = any(str(v).lower().strip() == 'open' for v in val_list)
            is_closed = any(str(v).lower().strip() == 'closed' for v in val_list)
            
            if is_open:
                op_filters.append({key: {"operator": "o", "values": []}})
                continue
            elif is_closed:
                op_filters.append({key: {"operator": "c", "values": []}})
                continue

        if key in f_need_map:
            #op_key = f'{key}_id'
            dict_f = create_ID_map(key) #creates the dictionary only if it's needed

            #every key has a list (it can be null, of 1 element of more but still a list)
            for v in val_list:
                clean_v = v.lower().strip() #clean the single element
                id = dict_f.get(clean_v)

                if id:
                    mapped_values.append(str(id))
                else:
                    missing_entities.append(f"'value: {v}' for the parameter {key}")

        elif key in ['subject', 'name']:
            operator = '~' #operator to search the specific name

            for v in val_list:
                mapped_values.append(str(v).strip()) #doesn't need cleaning 'cause the name MUST be equal (with Uppers and lowers)

        else:
            for v in val_list:
                if key == 'id':
                    mapped_values.append(int(v)) #covers cases where the number of the id is not saved as an int
                else:
                    mapped_values.append(str(v).lower().strip())
    
        if mapped_values: #if the list is not empty
            final_part_url = {op_key: {"operator": operator, "values": mapped_values}}
            op_filters.append(final_part_url)

    #if there's at least ONE error it interrupts the creation of the filter
    if missing_entities:
        errors = ", ".join(missing_entities)
        return f"System Info: these entities requested by the user do not exist.{errors}."

    if op_filters:
        json_string = json.dumps(op_filters)
        #final_url = base_url + '?filters=' + json_string
        req = requests.Request('GET', base_url, params={"filters": json_string})
        final_url = req.prepare().url
    else:
        final_url = base_url
    
    return final_url

#function that does the actual request
def fetch_openproject_data(final_url):
    if final_url.startswith("System Info"):
        return final_url

    try:
        response = requests.get(final_url, auth=('apikey', api_key))
        response.raise_for_status() #to check for example the case of invalid filter values
        data = response.json()
        
        if data.get('total', 0) == 0:
            return "System Info: no result"
            
        #return data.get('_embedded', {}).get('elements', [])
        return data

    except requests.exceptions.HTTPError as err:
        if response.status_code == 400:
            return "System Info: invalid parameters or unsufficient permissions"
        else:
            return f"System Info: communication error, error: {response.status_code})."
            
    except Exception as e:
        return f"Error: {e}"


#TEST SECTION
generated_output = []
for i, q in enumerate(second_test_set_queries):
    print(f"query {i+1}: ", {q})
    try:
        generated_output.append(chain.invoke({"format_instructions": parser.get_format_instructions(), "user_query": q}))
    except Exception as e:
        print('error: ', e)
    
for i, go in enumerate(generated_output):
    #print(f'test: {i+1}')
    url = build_OP_URL(go)

    dati_finali = fetch_openproject_data(url)
    #print('DATI \n', dati_finali)
    with open(f"Data-Q{i}.json", "w") as file: #code to check the json obtained
        json.dump(dati_finali, file, indent=4)
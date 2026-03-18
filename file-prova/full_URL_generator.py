from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOllama(model='llama3.2', temperature=0)

template = """You are an API query constructor.
    Your task is to create a fully valid URL for the OpenProject API.
    The BASE URL of the request is: https://tirocinio-alba2.openproject.com/api/v3/
    
    You need to DEDUCE the other paramethers from the user query and then to ADD THEM at the end of the base url.
    
    FIRST you need to FIND the keyword in the user query to IDENTIFY the MACRO-SECTION, then you add the filters after the macro-section putting the ?filters= BEFORE the filters.
    The FORMAT you MUST follow for the FILTERS is: [{{ "<filter name>": {{ "operator": "<operator>", "values": [<value>, ...] }} }}, ...]
    
    In the end you will have something like this: https://tirocinio-alba2.openproject.com/api/v3/macro-section?filters=[{{ "<filter name>": {{ "operator": "<operator>", "values": [<value>, ...] }} }},...]
    
    EXAMPLE:
    user query -> What are the active projects?
    keyword -> projects
    filter -> active = t
    final URL -> https://tirocinio-alba2.openproject.com/api/v3/projects?filters=[{{"active": {{"operator":"=","values": ["t"] }}}}]
    
    AVAILABLE FILTERS AND OPERATORS RULES:
    - "=" : Is / Equal to
    - "!" : Is not
    - "*" : Any (Meaning the field is not empty/null)
    - "!*" : None (Meaning the field is empty/null)
    - "~" : Contains (For text search, like searching a name)

    ALLOWED FILTER KEYS DICTIONARY:
    Depending on the macro-section you identified, you can ONLY use the following filter keys:

    If macro-section is 'projects', you can use:
    - "active" (boolean 't' or 'f'): If the project is currently active.
    - "public" (boolean 't' or 'f'): If the project is visible to everyone.
    - "name" (text string): To search for a specific project name (use "~" operator).

    CRITICAL INSTRUCTION: 
    - DO NOT WRITE ANY PYTHON CODE. 
    - DO NOT WRITE FUNCTIONS.
    - DO NOT EXPLAIN YOUR REASONING.
    - YOU MUST OUTPUT ONLY THE RAW URL STARTING WITH "https://" AND NOTHING ELSE.
    
    User query: {user_query}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | llm | StrOutputParser()

# 3. TEST
print("--- TEST 1: LLM DIRECT URL GENERATION ---\n")
array_query = ["Show me all active projects", "List the public projects", "Find the project named Alpha",
               "What are the active public projects?", "Search for active projects containing the word migration",
               "Show me closed projects", "List all projects"]
#user_query = "Show me the active projects"

try:
    for i, query in enumerate(array_query):
        generated_url = chain.invoke({"user_query": query})
        print(f"Generated URL question numb. {i+1}:\n{generated_url}\n")
except Exception as e:
    print(f"Errore: {e}")
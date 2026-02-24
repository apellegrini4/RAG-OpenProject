from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOllama(model='llama3.2', temperature=0)

template = template = """You are an API query constructor.
    Your task is to create a fully valid URL for the OpenProject API.
    The BASE URL of the request is: https://tirocinio-alba2.openproject.com/api/v3/
    
    You need to DEDUCE the other paramethers from the user query and then to ADD THEM at the end of the base url.
    
    FIRST you need to FIND the keyword in the user query to IDENTIFY the MACRO-SECTION, then you add the filters after the macro-section putting the ?filters= BEFORE the filters.
    The FORMAT you MUST follow for the FILTERS is: [{{ "<filter name>": {{ "operator": "<operator>", "values": [<value>, ...] }} }}, ...]
    
    In the end you will have something like this: https://tirocinio-alba2.openproject.com/api/v3/macro-section?filters=[{{ "<filter name>": {{ "operator": "<operator>", "values": [<value>, ...] }} }},...]
    
    EXAMPLE:
    user query -> What are the active projects?
    keyword -> projects
    filter -> active = true
    final URL -> https://tirocinio-alba2.openproject.com/api/v3/projects?filters=[{{"active": {{"operator":"=","values": ["true"] }}}}]
    
    Generate ONLY the final url.
    
    User query: {user_query}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | llm | StrOutputParser()

# 3. TEST
print("--- TEST 1: LLM DIRECT URL GENERATION ---\n")
user_query = "Show me the active projects"

try:
    generated_url = chain.invoke({"user_query": user_query})
    print(f"Generated URL:\n{generated_url}\n")
except Exception as e:
    print(f"Errore: {e}")
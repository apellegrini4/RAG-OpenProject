from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

llm = ChatOllama(model="llama3.2", temperature=0)
parser = StrOutputParser()

template = """You are an API integration assistant.
Your ONLY task is to generate a fully qualified URL for the OpenProject API based on the user's query.

Base URL: https://tirocinio-alba2.openproject.com/api/v3/
Endpoint: 'projects'

Rule: To filter projects, OpenProject uses complex JSON encoded in the URL. 
Example for active projects: https://tirocinio-alba2.openproject.com/api/v3/projects?filters=[{{"active":{{"operator":"=","values":["true"]}}}}]

Generate ONLY the final URL string. Do not add any text, explanations, or quotes.

User query: {user_query}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | llm | parser

# 3. TEST
print("--- TEST 1: LLM DIRECT URL GENERATION ---\n")
user_query = "Show me the active projects"

try:
    generated_url = chain.invoke({"user_query": user_query})
    print(f"Generated URL:\n{generated_url}\n")
    print("ANALISI DEL PROBLEMA:")
    print("1. Il modello potrebbe sbagliare la codifica dei caratteri (URL encoding).")
    print("2. Spesso inventa filtri inesistenti o sbaglia la complessa sintassi delle parentesi quadre/graffe richieste da OpenProject.")
except Exception as e:
    print(f"Errore: {e}")
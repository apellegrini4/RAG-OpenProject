import json
import urllib.parse
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# 1. DEFINIZIONE DEL CONTRATTO (Pydantic) - Solo per i Progetti per ora
class ProjectFilter(BaseModel):
    is_active: bool = Field(description="Set to true if the user wants active projects, false if closed/archived. Default to true if not specified.", default=True)
    search_keyword: str = Field(description="Any specific name or keyword mentioned to search for a project. Leave empty if none.", default="")

# 2. SETUP MODELLO E PARSER
parser = JsonOutputParser(pydantic_object=ProjectFilter)
llm = ChatOllama(model="llama3.2", format="json", temperature=0)

# 3. IL PROMPT (Semplice, con Few-Shot)
template = """You are an API Router for a Project Management system.
Extract the filter conditions from the user query.

EXAMPLE 1:
User: "Show me active projects"
Output: {{"is_active": true, "search_keyword": ""}}

EXAMPLE 2:
User: "Find the Alpha project"
Output: {{"is_active": true, "search_keyword": "Alpha"}}

{format_instructions}

User query: {user_query}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | llm | parser

# 4. TEST E COSTRUZIONE IN PYTHON
print("--- TEST 2: STRUCTURED EXTRACTION + PYTHON URL BUILDER ---\n")
user_query = "I want to see the active projects"

print(f"User asking: '{user_query}'\n")

# A. L'AI fa la sua parte (Estrazione intelligente)
ai_result = chain.invoke({
    "user_query": user_query,
    "format_instructions": parser.get_format_instructions()
})
print(f"1. LLM Extracted JSON: {ai_result}")

# B. Python fa la sua parte (Costruzione rigorosa dell'URL)
base_url = "https://tirocinio-alba.openproject.com/api/v3/projects"
op_filters = []

# Traduciamo il JSON dell'AI nel formato malato di OpenProject
if ai_result.get("is_active"):
    op_filters.append({"active": {"operator": "=", "values": ["true"]}})

# Convertiamo in stringa JSON e facciamo l'URL Encoding (sostituisce gli spazi con %20 ecc.)
filters_json_string = json.dumps(op_filters)
encoded_filters = urllib.parse.quote(filters_json_string)

final_url = f"{base_url}?filters={encoded_filters}"

print("\n2. Python Built URL:")
print(final_url)
print("\nANALISI DEL SUCCESSO:")
print("Python ha garantito che l'URL fosse formattato perfettamente secondo lo standard HTTP (URL encoding), cosa che l'LLM spesso fallisce a fare da solo.")
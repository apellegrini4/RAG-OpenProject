from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# 1. THE NEW SCHEMA: ENDPOINT + PARAMETERS
class APIRequest(BaseModel):
    endpoint: str = Field(
        description="The API endpoint to call. CHOOSE ONLY FROM THESE OPTIONS: 'work_packages' (for tasks, bugs, tickets), 'projects' (for project information), 'users' (for users, teams, people)."
    )
    filters: dict = Field(
        description="A key-value dictionary with the filters to apply. Example: {'status': 'open'} or {'search': 'keyword'}. Leave empty {} if there are no obvious filters."
    )
    explanation: str = Field(
        description="A very brief explanation (1 line) of why you chose this endpoint."
    )

# 2. INITIALIZATION (Using the lightweight llama3.2 model)
parser = JsonOutputParser(pydantic_object=APIRequest)
llm = ChatOllama(model="llama3.2", format="json", temperature=0)

# 3. THE "UNIVERSAL ROUTER" PROMPT
template = """You are the OpenProject API Router.
Your task is to map the user's query to the correct API endpoint and deduce any filters.

{format_instructions}

User query: {user_query}
"""
prompt = ChatPromptTemplate.from_template(template)

# 4. CREATE THE CHAIN
router_chain = prompt | llm | parser

# ==========================================
# 5. LET'S TEST THE FLEXIBILITY
# ==========================================
print("--- API ROUTER TEST STARTED ---\n")

test_questions = [
    "Show me all urgent tasks", 
    "What are the currently active projects?",
    "Who is Alba Pellegrini?"
]

for question in test_questions:
    print(f"User: '{question}'")
    try:
        # Invoke the chain
        result = router_chain.invoke({
            "user_query": question,
            "format_instructions": parser.get_format_instructions()
        })
        
        print(f"Chosen Endpoint: {result.get('endpoint')}")
        print(f"Filters: {result.get('filters')}")
        print(f"Reason: {result.get('explanation')}\n")
        print("-" * 40)
        
    except Exception as e:
        print(f"Parsing error: {e}")
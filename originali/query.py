#modulo che ELABORA le query degli utenti generando più versioni di essa, recuperando
#documenti pertinenti e fornendo risposte in base al contesto
import os
from langchain_community.chat_models import ChatOllama
#from langchain.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
#from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_classic.retrievers import MultiQueryRetriever
from originali.get_vector_db import get_vector_db

LLM_MODEL = os.getenv('LLM_MODEL', 'gemma3:1b')

# Function to get the prompt templates for generating alternative questions and answering based on context
def get_prompt():
    QUERY_PROMPT = PromptTemplate(
        input_variables=["question"],
#        template="""You are an AI language model assistant. Your task is to generate five
#        different versions of the given user question to retrieve relevant documents from
#        a vector database. By generating multiple perspectives on the user question, your
#        goal is to help the user overcome some of the limitations of the distance-based
#        similarity search. Provide these alternative questions separated by newlines.
#        Original question: {question}""",
        template="""Sei un assistente di modelli linguistici basati sull'intelligenza artificiale che estrae informazioni da ducmenti sulla gestione progettuale. Il tuo compito è generare cinque
        diverse versioni della domanda dell'utente per recuperare documenti pertinenti da
        un database vettoriale. Generando più prospettive sulla domanda dell'utente, il tuo
        obiettivo è aiutare l'utente a superare alcune delle limitazioni della ricerca per similarità basata sulla distanza. Fornisci queste domande alternative separate da nuove righe.
        Domanda originale: {question}""",
    )

    #template = """Answer the question based ONLY on the following context:
    template = """Sei un assistente di Project Management preciso e analitico. Rispondi basandoti SOLO sui documenti forniti.
    
    ATTENZIONE: Nel contesto troverai diversi ticket separati. Non mischiare MAI i dati di due ticket diversi.
    Se la domanda richiede un confronto:
    1. Analizza ogni ticket separatamente.
    2. Confronta i valori solo alla fine.

    GERARCHIA PRIORITÀ (dalla più alta):
    1. IMMEDIATA (Massima priorità)
    2. ALTA
    3. NORMALE
    4. BASSA   

    Se ti viene chiesto un campo specifico riporta il valore inerente a quella chiave.
    NON RIPETERE MAI LA DOMANDA DELL'UTENTE NEL CAMPO RISPOSTA, estrai solo il valore.
    Se un dato è "None" o "None%" o vuoto, rispondi "Il dato richiesto non è specificato", non inventare numeri.
    Le date hanno il formato AAAA-MM-GGTHH:MM:SS (Anno-Mese-Giorno), se devi paragonarle fai così:
    1. Confronta prima l'Anno (AAAA). Chi ha il numero più basso è più vecchio.
    2. Se l'anno è uguale, confronta il Mese (MM).
    3. Se il mese è uguale, confronta il Giorno (GG).
    4. Esempio: "2026-02-10" viene PRIMA (è meno recente) di "2026-02-11".

    Sii breve e diretto.
    FORMATO RISPOSTA OBBLIGATORIO:
    Quando identifichi un task/attività, devi SEMPRE specificare:
    1. L'ID del Ticket
    2. L'oggetto esatto
    3. Il dato/numero/testo richiesto dall'utente

    Contesto:
    {context}
    Domanda: {question}
    """
    #Question: {question}
    #"""

    prompt = ChatPromptTemplate.from_template(template)

    return QUERY_PROMPT, prompt

# Main function to handle the query process
def query(input):
    if input:
        # Initialize the language model with the specified model name
        llm = ChatOllama(model=LLM_MODEL, temperature=0) #provo a impedirgli di inventare
        # Get the vector database instance
        db = get_vector_db()
        # Get the prompt templates
        QUERY_PROMPT, prompt = get_prompt()

        # Set up the retriever to generate multiple queries using the language model and the query prompt
        retriever = MultiQueryRetriever.from_llm(
            db.as_retriever(), 
            llm,
            prompt=QUERY_PROMPT
        )

        # Define the processing chain to retrieve context, generate the answer, and parse the output
        chain = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser() #estrae il contenuto del messaggio e lo trasforma in una semplice string
        )

        #response = chain.invoke(input)

        #return response
        #---PICCOLA MODIFICA PER VERIFICARE COSA STA LEGGENDO L'AI
        # --- MODIFICA DEBUG ---
        # Vediamo quali pezzi di testo ha trovato il database
        #docs = retriever.invoke(input)
        #print(f"\n--- CONTESTO RECUPERATO ({len(docs)} chunks) ---")
        #for i, doc in enumerate(docs):
        #    print(f"\nCHUNK {i+1}:\n{doc.page_content}\n----------------")
        ## ----------------------

        # Esegui la catena
        response = chain.invoke(input)
        return response
        

    return None
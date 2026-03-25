#modulo che INIZIALIZZA e RESTITUISCE l'istanza del DATABASE VETTORIALE usata per archiviare
#e recuperare i document embeddings 
import os
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores.chroma import Chroma

CHROMA_PATH = os.getenv('CHROMA_PATH', 'chroma')
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'local-rag')
TEXT_EMBEDDING_MODEL = os.getenv('TEXT_EMBEDDING_MODEL', 'nomic-embed-text')

def get_vector_db():
    embedding = OllamaEmbeddings(model=TEXT_EMBEDDING_MODEL,show_progress=True)
    db = Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=CHROMA_PATH,
        embedding_function=embedding
    )
    #per ogni chunk Chroma restituisce un vettore numerico
    return db
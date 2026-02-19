#modulo che gestisce il PROCESSO di EMBEDDING, incluso il salvataggio dei file caricati,
#il caricamento e la suddivisione dei dati e l'aggiunta di documenti al database vettoriale
import os
from datetime import datetime
from werkzeug.utils import secure_filename
#from langchain_community.document_loaders import UnstructuredPDFLoader
#from langchain_community.document_loaders import PyPDFLoader
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from get_vector_db import get_vector_db

TEMP_FOLDER = os.getenv('TEMP_FOLDER', './_temp')

## Function to check if the uploaded file is allowed
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'txt'}

# Function to save the uploaded file to the temporary folder
def save_file(file):
    # Save the uploaded file with a secure filename and return the file path
    ct = datetime.now()
    ts = ct.timestamp()
    filename = str(ts) + "_" + secure_filename(file.filename)
    file_path = os.path.join(TEMP_FOLDER, filename)
    file.save(file_path)

    return file_path

# Function to load and split the data
def load_and_split_data(file_path):

    loader = TextLoader(file_path=file_path)
    data = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=7500, chunk_overlap=100)
    chunks = text_splitter.split_documents(data) #ottengo unità semantiche indicizzabili

    return chunks

# Main function to handle the embedding process
def embed(file):
    # Check if the file is valid, save it, load and split the data, add to the database, and remove the temporary file
    if file.filename != '' and file and allowed_file(file.filename):
        file_path = save_file(file)
        chunks = load_and_split_data(file_path)
        db = get_vector_db()
        db.add_documents(chunks) #salva i vettori in Chroma
        db.persist() #salva su disco
        os.remove(file_path)

        return True

    return False
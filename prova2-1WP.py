import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()
BASE_URL = os.getenv('OP_URL')
API_KEY = os.getenv('OP_API_KEY')
AUTH = HTTPBasicAuth('apikey', API_KEY)
HEADERS = {'Accept': 'application/json'}

def safe_get(data, keys_path, default="Non specificato"):
    current_level = data

    #segue il percordo di un dizionario annidato
    for key in keys_path:
        if isinstance(current_level, dict):
            current_level = current_level.get(key)
            if current_level is None:
                return default
        else:
            return default
    return current_level

def extract_single_wp(id):
    url = f"{BASE_URL}/api/v3/work_packages/{id}"
    
    #gestione degli errori
    try:
        response = requests.get(url, auth=AUTH, headers=HEADERS)
        response.raise_for_status()
    except Exception as e:
        print(f"Errore chiamata API: {e}")
        return

    wp = response.json()

    #creazione del dizionario    
    datas = {
        'ID': wp.get('id'),
        'subject': wp.get('subject'),
        'description': wp.get('description', {}).get('raw', 'Nessuna descrizione'), 
        'start_date': wp.get('startDate', 'Non definita'),
        'dueDate': wp.get('dueDate', 'Non definita'),
        'percentageDone': wp.get('percentageDone', 0),
        'updated_at': wp.get('updatedAt'),
        
        #per questi parametri devo necessariamente utilizzare la funzione generalizzata
        'priority': safe_get(wp, ['_embedded', 'priority', 'name']),
        'status': safe_get(wp, ['_embedded', 'status', 'name']),
        'project': safe_get(wp, ['_embedded', 'project', 'name']),
        'assignee': safe_get(wp, ['_embedded', 'assignee', 'name'], default="Nessuno"),
        'author': safe_get(wp, ['_links', 'author', 'name']),
        'type': safe_get(wp, ['_embedded', 'type', 'name'])
    }


    documento_rag = f"""
    ID: {datas['ID']}
    oggetto: {datas['subject']}
    tipo: {datas['type']}
    progetto: {datas['project']}
    stato: {datas['status']} (Completamento: {datas['percentageDone']}%)
    priorità: {datas['priority']}
    assegnatario: {datas['assignee']}
    autore: {datas['author']}
    data di inizio: {datas['start_date']}
    scadenza: {datas['dueDate']}
    ultima modifica: {datas['updated_at']}

    descrizione:
    {datas['description']}
    """

    #salvataggio su file e creazione cartella
    dir_path = "./data"
    if not os.path.exists(dir_path): os.makedirs(dir_path)
    
    file_name = f"data{id}.txt"
    file_path = os.path.join(dir_path, file_name)

    file = open(file_path, "w")
    file.write(documento_rag)
    file.close()

    #print(documento_rag)

if __name__ == '__main__':
    extract_single_wp(13)
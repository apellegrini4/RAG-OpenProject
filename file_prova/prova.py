import os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth

#carico i dati dal file .env per motivi di sicurezza
load_dotenv()
URL = os.getenv('OP_URL')
API_KEY = os.getenv('OP_API_KEY')

def get_projects():
    try:
        #creazione dell'url completo
        url = URL + '/api/v3/projects'

        basic = HTTPBasicAuth('apikey', API_KEY)
        headers = {
            'Accept': 'application/json'
        }

        response = requests.get(url, auth=basic, headers=headers)

        #decoder JSON built-in, crea un dizionario python
        data = response.json()

        #{} dopo a embedded serve per restituire una lista vuota e non bloccarsi in caso di errore,
        #stessa cosa nel caso di elements che deve contenere una lista, se è vuoto restituisce una lista vuota
        projects = data.get('_embedded', {}).get('elements', [])

        #for prog in projects:
        #    print("ID: ", prog['id'], "Name: ", prog['name'], "stato:")

        return data
    #gestisco il caso in cui una richiesta NON venga elaborata con successo
    except requests.exceptions.HTTPError as err:
        print("Errore HTTP: ", err)


if __name__ == '__main__':
    get_projects()
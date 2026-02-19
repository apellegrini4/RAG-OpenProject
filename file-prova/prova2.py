#file con request centralizzate per non ripetere codice
import os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth


#carico i dati dal file .env per motivi di sicurezza
load_dotenv()
URL = os.getenv('OP_URL')
API_KEY = os.getenv('OP_API_KEY')

def op_get(endpoint):
    url = URL + endpoint
    basic = HTTPBasicAuth('apikey', API_KEY)
    headers = {'Accept': 'application/json'}

    response = requests.get(url, auth=basic, headers=headers)
    response.raise_for_status()
    return response.json()

def get_projects():
    data = op_get('/api/v3/projects')
    projects = data.get('_embedded', {}).get('elements', [])
    return projects

def get_work_packages(project):
    #recupero il link
    wp_href = project['_links']['workPackages']['href']

    #passo il link relativo che verrà aggiunto all'URL da op_get
    data = op_get(wp_href)

    return data.get('_embedded', {}).get('elements', [])


if __name__ == '__main__':
    projects = get_projects()

    #facciamo la prova con 1 solo progetto
    if projects:
        first_project = projects[1]
        print("Progetto:", first_project['name'])

        try:
            work_packages = get_work_packages(first_project)

            for wp in work_packages:
                print("-", wp['subject'])

        except KeyError as e:
            print(f"Key error: {e} not found in the JSON response")

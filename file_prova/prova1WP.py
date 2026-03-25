import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv



load_dotenv()

BASE_URL = os.getenv('OP_URL')
API_KEY = os.getenv('OP_API_KEY')
AUTH = HTTPBasicAuth('apikey', API_KEY)
HEADERS = {'Accept': 'application/json'}



def extract_single_wp(id):

    url = f"{BASE_URL}/api/v3/work_packages/{id}"

    response = requests.get(url, auth=AUTH, headers=HEADERS)

    #jsonifico la risposta
    wp = response.json()

    #for k, v in wp.items():
    # print(k, v)

    #dati che voglio recuperare
    ID = wp['id']
    subject = wp['subject']
    description = wp['description']['raw']
    #print(description)
    priority = wp['_embedded']['priority']['name']
    start_date = wp['startDate']
    dueDate = wp['dueDate']
    percentageDone = wp['percentageDone']
    type = wp['_links']['type']['title']
    #print(type)
    status = wp['_embedded']['status']['name']

    updated_at = wp['updatedAt']
    project = wp['_embedded']['project']['name']
    assignee = wp['_embedded']['assignee']['name']
    author = wp['_links']['author']['title']

    #creo il documento
    documento_rag = f"""
    ID: {ID}
    subject: {subject}
    description: {description}
    priority: {priority}
    start_date: {start_date}
    dueDate: {dueDate}
    percentageDone = {percentageDone}
    type: {type}
    status: {status}
    updated_at: {updated_at}
    project: {project}
    assignee: {assignee}
    author: {author}
    """

    print(documento_rag)

if __name__ == '__main__':
    extract_single_wp(2)


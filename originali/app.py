#file principale per l'applicazione Flask, definisce i percorsi dai file di embedding al database vettoriale
#e per recuperare la risposta del modello 
import os
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify
from file_prova.embed2 import embed
from originali.query import query
from originali.get_vector_db import get_vector_db

TEMP_FOLDER = os.getenv('TEMP_FOLDER', './_temp')
os.makedirs(TEMP_FOLDER, exist_ok=True)

app = Flask(__name__) #inizializza l'app Flask

#configuro globalmente la NON conversione dei caratteri ascii in sequenze di escape
app.json.ensure_ascii = False

#2 servizi:

#@app.route decoratore serve per 'dire' che la funzione deve essere chiamata quando
#arriva una richiesta HTTP a questo URL
@app.route('/embed', methods=['POST'])
#servizio 1) ingestione dei dati (viene costruita la base di conoscenza)
def route_embed():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file'] #recupera il file caricato

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    embedded = embed(file) #RAG ingestion

    if embedded:
        return jsonify({"message": "File embedded successfully"}), 200

    return jsonify({"error": "File embedded unsuccessfully"}), 400

@app.route('/query', methods=['POST'])
#servizio 2) interrogazione (utilizzo della base della conoscenza)
def route_query():
    data = request.get_json() #recupera l'input contenente la query che è in formato json
    response = query(data.get('query')) #RAG retrieval + generation

    if response:
        return jsonify({"message": response}), 200

    return jsonify({"error": "Something went wrong"}), 400

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080, debug=True)
# app.py

from flask import Flask, request
from main_agent import ejecutar_agente
from flask_cors import CORS
from routes.whtp_webhook import webhook_bp
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
CORS(app, origins="*")

# Registrar el webhook de WhatsApp
app.register_blueprint(webhook_bp)

@app.route("/mensaje", methods=["POST"])
def mensaje():
    data = request.get_json()
    texto = data.get("texto", "")
    respuesta = ejecutar_agente(texto)
    return {"respuesta": respuesta}

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

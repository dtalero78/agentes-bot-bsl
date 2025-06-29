from flask import Blueprint, request, jsonify
import requests
import os
import time
import re
import openai

from main_agent import ejecutar_agente
import tools.validar_pago as validar_pago
import tools.consultar_cita as consultar_cita
from tools.pdf_sender import generar_pdf, send_pdf, marcar_pagado
from utils.upload_to_imgbb import upload_image_to_imgbb

load_dotenv = None  # ya lo cargas en app.py
WEBHOOK_URL = "https://gate.whapi.cloud/messages/text"
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
BOT_NUMBER = "573008021701"

webhook_bp = Blueprint('webhook', __name__)
imagenes_pendientes = {}

def descargar_imagen_whatsapp(image_id, intentos=3, espera=2):
    media_url = f"https://gate.whapi.cloud/media/{image_id}"
    for i in range(intentos):
        resp = requests.get(media_url, headers={"Authorization": f"Bearer {WHAPI_TOKEN}"})
        if resp.status_code == 200 and len(resp.content) > 1000:
            return resp.content
        time.sleep(espera)
    return None

def ocr_y_clasifica(imagen_url: str):
    """
    Devuelve (doc_type, transcript)
    doc_type: comprobante_pago | examen_medico | cita_confirmada | otro
    transcript: texto extraído de la imagen
    """
    # 1) OCR
    try:
        ocr = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": imagen_url}},
                    {"type": "text", "text": "Extrae todo el texto de esta imagen, respóndelo sin explicaciones."}
                ]
            }],
            max_tokens=500
        )
        texto = ocr.choices[0].message.content.strip()
    except Exception as e:
        print("❌ OCR falló:", e)
        return "otro", ""
    t = texto.lower()
    # 2) normalizo y limpio puntuación
    t_clean = re.sub(r'[.,]', ' ', t)

    # 3) patrones de comprobante de pago
    patrones_pago = [
        r'\bvalor\b', r'\btransferencia\b', r'\bdetalle del movimiento\b',
        r'\bnequi\b', r'\bbancolombia\b', r'\bdaviplata\b', r'\bcop\b',
        r'\$\s*\d+'
    ]
    for pat in patrones_pago:
        if re.search(pat, t_clean):
            return "comprobante_pago", texto

    # 4) patrones de examen médico
    if re.search(r'\bexamen\b|\boptometr|\bosteomuscul', t_clean):
        return "examen_medico", texto

    # 5) confirmación de cita
    if "cita" in t_clean and re.search(r'\d{1,2}[:h]\d{2}', t_clean):
        return "cita_confirmada", texto

    return "otro", texto

def send_whatsapp(to, body):
    requests.post(WEBHOOK_URL,
        headers={"Authorization": f"Bearer {WHAPI_TOKEN}", "Content-Type": "application/json"},
        json={"to": to, "body": body}
    )

@webhook_bp.route("/webhook", methods=["POST"])
def recibir_mensaje():
    data = request.get_json()
    # 0) Filtro eventos
    if data.get("event", {}).get("type") != "messages":
        return jsonify(status="no procesado"), 200

    msg = data["messages"][0]
    chat_id = msg.get("chat_id")
    if not chat_id:
        return jsonify(error="chat_id faltante"), 400
    user = chat_id.split("@")[0]
    from_me = msg.get("from_me", False)
    sender = msg.get("from")
    tipo = msg.get("type")
    texto = msg.get("text", {}).get("body", "") or ""

    # 1) STOP / reactivar
    txt = texto.strip().lower()
    if from_me and sender == BOT_NUMBER:
        if txt.startswith("...transfiriendo con asesor"):
            requests.post("https://www.bsl.com.co/_functions/actualizarObservaciones",
                          json={"userId": user, "observaciones": "stop"})
            return jsonify(status="bot detenido"), 200
        if txt.startswith("...te dejo con el bot"):
            requests.post("https://www.bsl.com.co/_functions/actualizarObservaciones",
                          json={"userId": user, "observaciones": " "})
            return jsonify(status="bot reactivado"), 200
        return jsonify(status="control procesado"), 200

    # 2) guardo mensaje en Wix
    requests.post("https://www.bsl.com.co/_functions/guardarConversacion",
                  json={"userId": user, "nombre": msg.get("from_name",""), 
                        "mensajes":[{"from":"usuario","mensaje": texto or "📷 Imagen"}]})

    # 3) compruebo si está detenido
    estado = requests.get(f"https://www.bsl.com.co/_functions/obtenerConversacion?userId={user}").json() or {}
    if estado.get("stopBot") or estado.get("observaciones")=="stop":
        return jsonify(status="bot inactivo"), 200

    # 4) flujo imagen
    if tipo == "image":
        img_id = msg["image"]["id"]
        img_data = descargar_imagen_whatsapp(img_id)
        if not img_data:
            send_whatsapp(user, "No pude descargar la imagen, inténtalo de nuevo.")
            return jsonify(status="error"),200

        # 🔔 Mensaje inmediato antes de procesar imagen
        send_whatsapp(user, "🔎... un momento por favor")
        time.sleep(0.3)  # Pequeña pausa para asegurar orden, opcional

        # subo a imgbb
        try:
            url = upload_image_to_imgbb(img_data)
        except:
            send_whatsapp(user, "Error subiendo la imagen, inténtalo de nuevo.")
            return jsonify(status="error"),200

        # clasifico
        doc_type, transcript = ocr_y_clasifica(url)

        if doc_type=="examen_medico":
            send_whatsapp(user, f"Texto detectado:\n{transcript}")
            # delego al agente para respuesta de exámenes
            resp, thread = ejecutar_agente(
                texto_usuario="Lista de exámenes detectada, dime la información sobre estos.",
                thread_id=estado.get("threadId"),
                imagen_url=url
            )
            send_whatsapp(user, resp)
            # guardo en Wix
            requests.post("https://www.bsl.com.co/_functions/guardarConversacion",
                          json={"userId": user, "nombre":"sistema","mensajes":[{"from":"sistema","mensaje":resp}],"threadId":thread})
            return jsonify(status="ok"),200

        if doc_type=="cita_confirmada":
            # extraigo fecha/hora con regex
            m = re.search(r'(\d{1,2}(?:[:h]\d{2}).+?)(?: a |$)', transcript)
            fecha = m.group(1) if m else transcript
            resp = f"✅ Tu cita está programada para: {fecha}"
            send_whatsapp(user, resp)
            requests.post("https://www.bsl.com.co/_functions/guardarConversacion",
                          json={"userId":user,"nombre":"sistema","mensajes":[{"from":"sistema","mensaje":resp}]})
            return jsonify(status="ok"),200

        if doc_type=="comprobante_pago":
            # pido cédula para validar pago
            msg_pide = "Para validar tu pago, por favor envía tu número de documento (solo dígitos)."
            send_whatsapp(user, msg_pide)
            imagenes_pendientes[user] = {"url":url}
            requests.post("https://www.bsl.com.co/_functions/guardarConversacion",
                          json={"userId":user,"nombre":"sistema","mensajes":[{"from":"sistema","mensaje":msg_pide}]})
            return jsonify(status="ok"),200

        # caso otro
        send_whatsapp(user, "No reconozco el contenido de esa imagen. ¿Puedes enviarme el documento correcto?")
        return jsonify(status="ok"),200

    # 5) flujo número de doc tras comprobante
    pending = imagenes_pendientes.get(user)
    if pending and pending.get("url"):
        if texto.isdigit():
            send_whatsapp(user, "🔎... un momento por favor")
            url = pending["url"]
            # tomo thread si existe
            thread_id = estado.get("threadId")
            # delego a validar_pago
            resultado = validar_pago.run(imagen_url=url, numeroId=texto, whatsapp_id=user, thread_id=thread_id)
            send_whatsapp(user, resultado)
            # guardo en Wix
            requests.post("https://www.bsl.com.co/_functions/guardarConversacion",
                          json={"userId":user,"nombre":"sistema","mensajes":[{"from":"sistema","mensaje":resultado}],"threadId":thread_id})
            imagenes_pendientes.pop(user,None)
            return jsonify(status="pdf_enviado"),200
        else:
            err = "❗️ Envía solo tu número de documento (solo dígitos)."
            send_whatsapp(user, err)
            return jsonify(status="esperando_doc"),200

    # 6) caso texto normal → delegado al agente
    resp, thread = ejecutar_agente(texto, thread_id=estado.get("threadId"))
    send_whatsapp(user, resp)
    requests.post("https://www.bsl.com.co/_functions/guardarConversacion",
                  json={"userId":user,"nombre":"sistema","mensajes":[{"from":"sistema","mensaje":resp}],"threadId":thread})
    return jsonify(status="ok"),200

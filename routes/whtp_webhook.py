from flask import Blueprint, request, jsonify
import requests
import os
import time
import re
import openai
import threading

from main_agent import ejecutar_agente
import tools.validar_pago as validar_pago
import tools.consultar_cita as consultar_cita
from tools.pdf_sender import generar_pdf, send_pdf, marcar_pagado
from utils.upload_to_imgbb import upload_image_to_imgbb

WEBHOOK_URL = "https://gate.whapi.cloud/messages/text"
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
BOT_NUMBER = "573008021701"

webhook_bp = Blueprint('webhook', __name__)
imagenes_pendientes = {}

def descargar_imagen_whatsapp(image_id, intentos=3, espera=2):
    media_url = f"https://gate.whapi.cloud/media/{image_id}"
    for i in range(intentos):
        print(f"Intento {i+1} de descarga imagen: {media_url}")
        resp = requests.get(media_url, headers={"Authorization": f"Bearer {WHAPI_TOKEN}"})
        print(f"Intento {i+1}: status={resp.status_code}, len={len(resp.content)}")
        if resp.status_code == 200 and len(resp.content) > 1000:
            print("✅ Imagen descargada correctamente.")
            return resp.content
        print("Contenido devuelto:", resp.content[:100])
        time.sleep(espera)
    print("❌ No se pudo descargar imagen. Último status:", resp.status_code)
    return None

def ocr_y_clasifica(imagen_url: str):
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
    t_clean = re.sub(r'[.,]', ' ', t)
    patrones_pago = [
        r'\bvalor\b', r'\btransferencia\b', r'\bdetalle del movimiento\b',
        r'\bnequi\b', r'\bbancolombia\b', r'\bdaviplata\b', r'\bcop\b',
        r'\$\s*\d+'
    ]
    for pat in patrones_pago:
        if re.search(pat, t_clean):
            return "comprobante_pago", texto
    if re.search(r'\bexamen\b|\boptometr|\bosteomuscul', t_clean):
        return "examen_medico", texto
    if "cita" in t_clean and re.search(r'\d{1,2}[:h]\d{2}', t_clean):
        return "cita_confirmada", texto
    return "otro", texto

def send_whatsapp(to, body):
    if not body:
        body = "⚠️ No se pudo obtener respuesta para este mensaje. Intenta de nuevo."
    print(f"Enviando mensaje a {to}: {body[:100]}")
    requests.post(WEBHOOK_URL,
        headers={"Authorization": f"Bearer {WHAPI_TOKEN}", "Content-Type": "application/json"},
        json={"to": to, "body": body}
    )

def procesar_imagen_en_background(user, img_data, estado):
    try:
        print("🔄 Subiendo imagen a imgbb...")
        url = upload_image_to_imgbb(img_data)
        print(f"✅ Imagen subida a imgbb: {url}")
    except Exception as e:
        print("❌ Error subiendo imagen:", e)
        send_whatsapp(user, "Error subiendo la imagen, inténtalo de nuevo.")
        return

    doc_type, transcript = ocr_y_clasifica(url)
    print(f"Tipo de doc detectado: {doc_type}")

    if doc_type == "examen_medico":
        send_whatsapp(user, f"Texto detectado:\n{transcript}")
        resp, thread = ejecutar_agente(
            texto_usuario="Lista de exámenes detectada, dime la información sobre estos.",
            thread_id=estado.get("threadId"),
            imagen_url=url
        )
        send_whatsapp(user, resp)
        requests.post("https://www.bsl.com.co/_functions/guardarConversacion", {
            "userId": user,
            "nombre": "sistema",
            "mensajes": [{"from": "sistema", "mensaje": resp}],
            "threadId": thread,
            "ultimoMensajeBot": resp
        })
        return

    if doc_type == "cita_confirmada":
        m = re.search(r'(\d{1,2}(?:[:h]\d{2}).+?)(?: a |$)', transcript)
        fecha = m.group(1) if m else transcript
        resp = f"✅ Tu cita está programada para: {fecha}"
        send_whatsapp(user, resp)
        requests.post("https://www.bsl.com.co/_functions/guardarConversacion", {
            "userId": user,
            "nombre": "sistema",
            "mensajes": [{"from": "sistema", "mensaje": resp}],
            "ultimoMensajeBot": resp
        })
        return

    if doc_type == "comprobante_pago":
        msg_pide = "Para validar tu pago, por favor envía tu número de documento (solo dígitos)."
        send_whatsapp(user, msg_pide)
        imagenes_pendientes[user] = {"url": url}
        requests.post("https://www.bsl.com.co/_functions/guardarConversacion", {
            "userId": user,
            "nombre": "sistema",
            "mensajes": [{"from": "sistema", "mensaje": msg_pide}],
            "ultimoMensajeBot": msg_pide
        })
        return

    send_whatsapp(user, "No reconozco el contenido de esa imagen. ¿Puedes enviarme el documento correcto?")

@webhook_bp.route("/webhook", methods=["POST"])
def recibir_mensaje():
    data = request.get_json()
    if data.get("event", {}).get("type") != "messages":
        print("Evento no es tipo mensaje")
        return jsonify(status="no procesado"), 200

    msg = data["messages"][0]
    chat_id = msg.get("chat_id")
    if not chat_id:
        print("Error: chat_id faltante")
        return jsonify(error="chat_id faltante"), 400
    user = chat_id.split("@")[0]
    estado = requests.get(f"https://www.bsl.com.co/_functions/obtenerConversacion?userId={user}").json() or {}
    from_me = msg.get("from_me", False)
    sender = msg.get("from")
    tipo = msg.get("type")
    texto = msg.get("text", {}).get("body", "") or ""

    print(f"Recibí mensaje tipo {tipo} de usuario {user}")

    txt = texto.strip().lower()

    if from_me and sender == BOT_NUMBER:
        print("Mensaje desde el propio bot (admin o sistema)")

        if txt.startswith("...transfiriendo con asesor"):
            requests.post("https://www.bsl.com.co/_functions/actualizarObservaciones", json={"userId": user, "observaciones": "stop"})
            return jsonify(status="bot detenido"), 200

        if txt.startswith("...te dejo con el bot"):
            requests.post("https://www.bsl.com.co/_functions/actualizarObservaciones", json={"userId": user, "observaciones": " "})
            return jsonify(status="bot reactivado"), 200

        if not txt.startswith("...") and texto != estado.get("ultimoMensajeBot"):
            requests.post("https://www.bsl.com.co/_functions/guardarConversacion", {
                "userId": user,
                "nombre": "admin",
                "mensajes": [{"from": "admin", "mensaje": texto}],
                "threadId": estado.get("threadId")
            })
            return jsonify(status="admin_guardado"), 200

        return jsonify(status="ignorado_para_evitar_duplicado"), 200

    requests.post("https://www.bsl.com.co/_functions/guardarConversacion", {
        "userId": user,
        "nombre": msg.get("from_name", ""),
        "mensajes": [{"from": "usuario", "mensaje": texto or "📷 Imagen"}]
    })

    if estado.get("stopBot") or estado.get("observaciones") == "stop":
        print("El bot está en estado detenido para este usuario.")
        return jsonify(status="bot inactivo"), 200

    if tipo == "image":
        img_id = msg["image"]["id"]
        print(f"Intentando descargar imagen de WhatsApp con id {img_id}")
        img_data = descargar_imagen_whatsapp(img_id)
        print(f"Resultado de descarga: {'OK' if img_data else 'FALLÓ'}")
        if not img_data:
            send_whatsapp(user, "No pude descargar la imagen, inténtalo de nuevo.")
            return jsonify(status="error"), 200

        send_whatsapp(user, "🔎... un momento por favor")
        threading.Thread(target=procesar_imagen_en_background, args=(user, img_data, estado)).start()
        return jsonify(status="procesando_en_background"), 200

    pending = imagenes_pendientes.get(user)
    if pending and pending.get("url"):
        if texto.isdigit():
            send_whatsapp(user, "🔎... un momento por favor")
            url = pending["url"]
            thread_id = estado.get("threadId")
            resultado = validar_pago.run(imagen_url=url, numeroId=texto, whatsapp_id=user, thread_id=thread_id)
            if not resultado:
                resultado = "⚠️ No se pudo validar el comprobante, intenta de nuevo."
            send_whatsapp(user, resultado)
            requests.post("https://www.bsl.com.co/_functions/guardarConversacion", {
                "userId": user,
                "nombre": "sistema",
                "mensajes": [{"from": "sistema", "mensaje": resultado}],
                "threadId": thread_id,
                "ultimoMensajeBot": resultado
            })
            imagenes_pendientes.pop(user, None)
            return jsonify(status="pdf_enviado"), 200
        else:
            err = "❗️ Envía solo tu número de documento (solo dígitos)."
            send_whatsapp(user, err)
            return jsonify(status="esperando_doc"), 200

    resp, thread = ejecutar_agente(texto, thread_id=estado.get("threadId"))
    if not resp:
        resp = "⚠️ No se pudo procesar tu solicitud, intenta de nuevo."

    send_whatsapp(user, resp)
    requests.post("https://www.bsl.com.co/_functions/guardarConversacion", {
        "userId": user,
        "nombre": "sistema",
        "mensajes": [{"from": "sistema", "mensaje": resp}],
        "threadId": thread,
        "ultimoMensajeBot": resp
    })

    return jsonify(status="ok"), 200

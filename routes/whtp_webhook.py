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

def send_whatsapp(to, body):
    if not body:
        body = "⚠️ No se pudo obtener respuesta para este mensaje. Intenta de nuevo."
    print(f"Enviando mensaje a {to}: {body[:100]}")
    requests.post(
        WEBHOOK_URL,
        headers={"Authorization": f"Bearer {WHAPI_TOKEN}", "Content-Type": "application/json"},
        json={"to": to, "body": body}
    )

def reenviar_a_openai(role, mensaje, thread_id):
    if not thread_id or not mensaje or not str(mensaje).strip():
        print(f"⚠️ No se reenvió mensaje vacío a OpenAI. thread_id={thread_id}, mensaje={repr(mensaje)}")
        return
    try:
        openai_role = {
            "usuario": "user",
            "sistema": "assistant",
            "admin": "assistant",   # O "system" si prefieres
            "wix": "assistant",
            "wix-automatico": "assistant",
        }.get(role, "assistant")
        if role not in ["usuario", "sistema"]:
            mensaje = f"[{role.upper()}]: {mensaje}"
        openai.beta.threads.messages.create(
            thread_id=thread_id,
            role=openai_role,
            content=mensaje
        )
    except Exception as e:
        print(f"❌ Error reenviando mensaje a OpenAI: {e}")

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
        resp, thread = ejecutar_agente(
            texto_usuario="Lista de exámenes detectada, dime la información sobre estos.",
            thread_id=estado.get("threadId"),
            imagen_url=url
        )
        send_whatsapp(user, resp)
        requests.post(
            "https://www.bsl.com.co/_functions/guardarConversacion",
            json={
                "userId": user,
                "nombre": "sistema",
                "mensajes": [{"from": "sistema", "mensaje": resp}],
                "threadId": thread
            }
        )
        reenviar_a_openai("sistema", resp, thread)
        requests.post(
            "https://www.bsl.com.co/_functions/actualizarEstado",
            json={"userId": user, "ultimoMensajeSistema": resp}
        )
        return

    if doc_type == "cita_confirmada":
        m = re.search(r'(\d{1,2}(?:[:h]\d{2}).+?)(?: a |$)', transcript)
        fecha = m.group(1) if m else transcript
        resp = f"✅ Tu cita está programada para: {fecha}"
        send_whatsapp(user, resp)
        requests.post(
            "https://www.bsl.com.co/_functions/guardarConversacion",
            json={
                "userId": user,
                "nombre": "sistema",
                "mensajes": [{"from": "sistema", "mensaje": resp}]
            }
        )
        reenviar_a_openai("sistema", resp, estado.get("threadId"))
        requests.post(
            "https://www.bsl.com.co/_functions/actualizarEstado",
            json={"userId": user, "ultimoMensajeSistema": resp}
        )
        return

    if doc_type == "comprobante_pago":
        msg_pide = "Para validar tu pago, por favor envía tu número de documento (solo dígitos)."
        send_whatsapp(user, msg_pide)
        imagenes_pendientes[user] = {"url": url}
        requests.post(
            "https://www.bsl.com.co/_functions/guardarConversacion",
            json={
                "userId": user,
                "nombre": "sistema",
                "mensajes": [{"from": "sistema", "mensaje": msg_pide}]
            }
        )
        reenviar_a_openai("sistema", msg_pide, estado.get("threadId"))
        requests.post(
            "https://www.bsl.com.co/_functions/actualizarEstado",
            json={"userId": user, "ultimoMensajeSistema": msg_pide}
        )
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
    estado = requests.get(
        f"https://www.bsl.com.co/_functions/obtenerConversacion?userId={user}"
    ).json() or {}

    from_me = msg.get("from_me", False)
    sender = msg.get("from")
    source = msg.get("source", "")
    tipo = msg.get("type")
    texto = msg.get("text", {}).get("body", "") or ""
    txt = texto.strip().lower()

    print(f"Recibí mensaje tipo {tipo} de usuario {user} (from_me={from_me}, source={source})")

    # --- Mensajes desde el propio bot/admin ---
    if from_me and sender == BOT_NUMBER:
        if source == "api":
            return jsonify(status="ignorado_echo_api"), 200
        if txt.startswith("...transfiriendo con asesor"):
            requests.post(
                "https://www.bsl.com.co/_functions/actualizarObservaciones",
                json={"userId": user, "observaciones": "stop"}
            )
            return jsonify(status="bot detenido"), 200
        if txt.startswith("...te dejo con el bot"):
            requests.post(
                "https://www.bsl.com.co/_functions/actualizarObservaciones",
                json={"userId": user, "observaciones": " "}
            )
            return jsonify(status="bot reactivado"), 200
        if not txt.startswith("...") and texto != estado.get("ultimoMensajeBot"):
            requests.post(
                "https://www.bsl.com.co/_functions/guardarConversacion",
                json={
                    "userId": user,
                    "nombre": "admin",
                    "mensajes": [{"from": "admin", "mensaje": texto}],
                    "threadId": estado.get("threadId")
                }
            )
            reenviar_a_openai("admin", texto, estado.get("threadId"))
            return jsonify(status="admin_guardado"), 200

        return jsonify(status="ignorado_para_evitar_duplicado"), 200

    # --- Mensajes de usuario ---
    requests.post(
        "https://www.bsl.com.co/_functions/guardarConversacion",
        json={
            "userId": user,
            "nombre": msg.get("from_name", ""),
            "mensajes": [{"from": "usuario", "mensaje": texto or "📷 Imagen"}]
        }
    )
    # *** NO reenvíes aquí a OpenAI ***
    # reenviar_a_openai("usuario", texto or "📷 Imagen", estado.get("threadId"))

    if estado.get("stopBot") or estado.get("observaciones") == "stop":
        print("El bot está detenido para este usuario.")
        return jsonify(status="bot inactivo"), 200

    # FLUJO para imágenes
    if tipo == "image":
        img_id = msg["image"]["id"]
        print(f"Descargando imagen con id {img_id}")
        img_data = descargar_imagen_whatsapp(img_id)
        if not img_data:
            send_whatsapp(user, "No pude descargar la imagen, inténtalo de nuevo.")
            return jsonify(status="error"), 200

        send_whatsapp(user, "🔎... un momento por favor")
        threading.Thread(target=procesar_imagen_en_background, args=(user, img_data, estado)).start()
        return jsonify(status="procesando_en_background"), 200

    # FLUJO comprobante de pago
    pending = imagenes_pendientes.get(user)
    if pending and pending.get("url"):
        if texto.isdigit():
            send_whatsapp(user, "🔎... un momento por favor")
            url = pending["url"]
            thread_id = estado.get("threadId")
            resultado = validar_pago_run(imagen_url=url, numeroId=texto, whatsapp_id=user, thread_id=thread_id)
            resultado = resultado or "⚠️ No se pudo validar el comprobante, intenta de nuevo."
            send_whatsapp(user, resultado)
            requests.post(
                "https://www.bsl.com.co/_functions/guardarConversacion",
                json={
                    "userId": user,
                    "nombre": "sistema",
                    "mensajes": [{"from": "sistema", "mensaje": resultado}],
                    "threadId": thread_id
                }
            )
            reenviar_a_openai("sistema", resultado, thread_id)
            requests.post(
                "https://www.bsl.com.co/_functions/actualizarEstado",
                json={"userId": user, "ultimoMensajeSistema": resultado}
            )
            imagenes_pendientes.pop(user, None)
            return jsonify(status="pdf_enviado"), 200
        else:
            err = "❗️ Envía solo tu número de documento (solo dígitos)."
            send_whatsapp(user, err)
            return jsonify(status="esperando_doc"), 200

    # FLUJO texto normal → agente
    resp, thread = ejecutar_agente(texto, thread_id=estado.get("threadId"))
    resp = resp or "⚠️ No se pudo procesar tu solicitud, intenta de nuevo."
    send_whatsapp(user, resp)
    requests.post(
        "https://www.bsl.com.co/_functions/guardarConversacion",
        json={
            "userId": user,
            "nombre": "sistema",
            "mensajes": [{"from": "sistema", "mensaje": resp}],
            "threadId": thread
        }
    )
    reenviar_a_openai("sistema", resp, thread)
    requests.post(
        "https://www.bsl.com.co/_functions/actualizarEstado",
        json={"userId": user, "ultimoMensajeSistema": resp}
    )
    return jsonify(status="ok"), 200

@webhook_bp.route("/reenviar_a_openai", methods=["POST"])
def endpoint_reenviar_a_openai():
    data = request.get_json()
    role = data.get("role")
    mensaje = data.get("mensaje")
    thread_id = data.get("thread_id")
    if not role or not mensaje or not thread_id:
        return jsonify({"success": False, "error": "Faltan datos obligatorios"}), 400
    try:
        reenviar_a_openai(role, mensaje, thread_id)
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

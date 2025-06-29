from flask import Blueprint, request, jsonify
import requests
import os
import time
from main_agent import ejecutar_agente
from tools.pdf_sender import generar_pdf, send_pdf, marcar_pagado
import tools.validar_pago as validar_pago
from utils.upload_to_imgbb import upload_image_to_imgbb

webhook_bp = Blueprint('webhook', __name__)

WHAPI_URL = "https://gate.whapi.cloud/messages/text"
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
BOT_NUMBER = "573008021701"

imagenes_pendientes = {}

def descargar_imagen_whatsapp(image_id, intentos=3, espera=2):
    media_url = f"https://gate.whapi.cloud/media/{image_id}"
    for intento in range(intentos):
        media_resp = requests.get(media_url, headers={"Authorization": f"Bearer {WHAPI_TOKEN}"})
        print(f"🔍 Intento {intento+1}: status {media_resp.status_code}, len {len(media_resp.content)}")
        if media_resp.status_code == 200 and len(media_resp.content) > 1000:
            print("✅ Imagen de WhatsApp descargada correctamente.")
            return media_resp.content
        print(f"⏳ Imagen muy pequeña o no disponible aún, esperando {espera} segundos antes de reintentar...")
        time.sleep(espera)
    print("❌ No se pudo obtener la imagen original de WhatsApp después de varios intentos.")
    return None

@webhook_bp.route("/webhook", methods=["POST"])
def recibir_mensaje():
    data = request.get_json()
    print("📥 Datos recibidos:", data)

    if data.get("event", {}).get("type") != "messages":
        return jsonify({"status": "evento no procesado"}), 200

    mensaje = data["messages"][0]
    chat_id = mensaje.get("chat_id")
    from_me = mensaje.get("from_me", False)
    numero_id = chat_id.split("@")[0] if chat_id else None  # ESTE ES WHATSAPP
    tipo = mensaje.get("type")
    texto = mensaje.get("text", {}).get("body", "") or ""
    nombre = mensaje.get("from_name", "SinNombre")
    sender_number = mensaje.get("from")

    print("📸 Tipo de mensaje:", tipo, "🔢 Número:", numero_id)

    if not numero_id:
        return jsonify({"error": "chat_id faltante"}), 400

    texto_limpio = texto.strip().lower()

    # --- MARCAR STOP ---
    if (
        from_me
        and sender_number == BOT_NUMBER
        and texto_limpio.startswith("...transfiriendo con asesor")
    ):
        requests.post("https://www.bsl.com.co/_functions/guardarConversacion", json={
            "userId": numero_id,
            "nombre": nombre,
            "mensajes": [{"from": "usuario", "mensaje": texto}]
        })
        requests.post("https://www.bsl.com.co/_functions/actualizarObservaciones", json={
            "userId": numero_id,
            "observaciones": "stop"
        })
        print(f"🚩 Usuario {numero_id} transferido con asesor, bot detenido.")
        return jsonify({"status": "bot detenido por transferencia"}), 200

    # --- DESMARCAR STOP ---
    if (
        from_me
        and sender_number == BOT_NUMBER
        and texto_limpio.startswith("...te dejo con el bot")
    ):
        requests.post("https://www.bsl.com.co/_functions/guardarConversacion", json={
            "userId": numero_id,
            "nombre": nombre,
            "mensajes": [{"from": "usuario", "mensaje": texto}]
        })
        requests.post("https://www.bsl.com.co/_functions/actualizarObservaciones", json={
            "userId": numero_id,
            "observaciones": " "
        })
        print(f"✅ Usuario {numero_id} reactivado, bot habilitado.")
        return jsonify({"status": "bot reactivado por admin"}), 200

    # Ignorar mensajes enviados por el bot/admin
    if from_me or sender_number == BOT_NUMBER:
        return jsonify({"status": "control procesado"}), 200

    # Guardar siempre el mensaje de usuario en Wix
    requests.post("https://www.bsl.com.co/_functions/guardarConversacion", json={
        "userId": numero_id,
        "nombre": nombre,
        "mensajes": [{"from": "usuario", "mensaje": texto or "📷 Imagen recibida"}]
    })

    # Consultar si el bot está detenido
    estado_resp = requests.get(f"https://www.bsl.com.co/_functions/obtenerConversacion?userId={numero_id}")
    estado = estado_resp.json() if estado_resp.status_code == 200 else {}
    if estado.get("stopBot") or estado.get("observaciones") == "stop":
        return jsonify({"status": "bot inactivo"}), 200

    # 1) Usuario envía imagen
    if tipo == "image":
        image_id = mensaje["image"]["id"]
        img_data = descargar_imagen_whatsapp(image_id)
        if not img_data:
            # Mensaje de error y detención
            requests.post(WHAPI_URL, headers={
                "Authorization": f"Bearer {WHAPI_TOKEN}",
                "accept": "application/json",
                "Content-Type": "application/json"
            }, json={"to": numero_id, "body": "No pude procesar tu comprobante. Intenta reenviar la imagen en unos segundos."})
            return jsonify({"status": "imgbb error"}), 200

        # SUBIR A IMGBB
        try:
            url_publica = upload_image_to_imgbb(img_data)
            print(f"🌐 Imagen subida a imgbb: {url_publica}")
        except Exception as e:
            print("❌ Error subiendo imagen a imgbb:", e)
            requests.post(WHAPI_URL, headers={
                "Authorization": f"Bearer {WHAPI_TOKEN}",
                "accept": "application/json",
                "Content-Type": "application/json"
            }, json={"to": numero_id, "body": "No pude procesar tu comprobante. Intenta de nuevo o envía otra imagen."})
            return jsonify({"status": "imgbb error"}), 200

        imagenes_pendientes[numero_id] = {"awaiting_doc": True, "url_publica": url_publica}

        # Mensaje: un momento por favor + luego pedir documento
        requests.post(WHAPI_URL, headers={
            "Authorization": f"Bearer {WHAPI_TOKEN}",
            "accept": "application/json",
            "Content-Type": "application/json"
        }, json={"to": numero_id, "body": "...un momento por favor"})
        requests.post(WHAPI_URL, headers={
            "Authorization": f"Bearer {WHAPI_TOKEN}",
            "accept": "application/json",
            "Content-Type": "application/json"
        }, json={"to": numero_id, "body": "✅ Hemos recibido tu comprobante. ¿Cuál es tu número de documento para generar el PDF?"})

        requests.post("https://www.bsl.com.co/_functions/guardarConversacion", json={
            "userId": numero_id,
            "nombre": "sistema",
            "mensajes": [
                {"from": "sistema", "mensaje": "Imagen recibida. Esperando documento para validar y generar certificado."}
            ]
        })

        return jsonify({"status": "esperando_documento"}), 200

    # 2) Usuario responde con su número de documento
    pending = imagenes_pendientes.get(numero_id)
    if pending and pending.get("awaiting_doc"):
        if texto.isdigit():
            url_publica = pending["url_publica"]

            # Recuperar thread_id de Wix si existe
            thread_id = None
            try:
                estado_resp = requests.get(f"https://www.bsl.com.co/_functions/obtenerConversacion?userId={numero_id}")
                estado = estado_resp.json() if estado_resp.status_code == 200 else {}
                thread_id = estado.get("threadId")
                print("🧩 threadId recuperado del backend:", thread_id)
            except Exception as e:
                print("⚠️ No se pudo recuperar thread_id:", e)
                thread_id = None

            # Enviar mensaje de espera
            requests.post(WHAPI_URL, headers={
                "Authorization": f"Bearer {WHAPI_TOKEN}",
                "accept": "application/json",
                "Content-Type": "application/json"
            }, json={"to": numero_id, "body": "...un momento por favor"})

            resultado = validar_pago.run(
                imagen_url=url_publica,
                numeroId=texto,
                whatsapp_id=numero_id,
                thread_id=thread_id
            )

            requests.post(WHAPI_URL, headers={
                "Authorization": f"Bearer {WHAPI_TOKEN}",
                "accept": "application/json",
                "Content-Type": "application/json"
            }, json={"to": numero_id, "body": resultado})

            requests.post("https://www.bsl.com.co/_functions/guardarConversacion", json={
                "userId": numero_id,
                "nombre": "sistema",
                "mensajes": [{"from": "sistema", "mensaje": resultado}],
                "threadId": thread_id
            })

            imagenes_pendientes.pop(numero_id, None)
            return jsonify({"status": "pdf_enviado"}), 200
        else:
            respuesta_final = "❗️ Por favor, envía únicamente tu número de documento (solo dígitos)."
            requests.post(WHAPI_URL, headers={
                "Authorization": f"Bearer {WHAPI_TOKEN}",
                "accept": "application/json",
                "Content-Type": "application/json"
            }, json={"to": numero_id, "body": respuesta_final})
            return jsonify({"status": "esperando_documento_valido"}), 200

    # 3) Caso normal: delegar al agente OpenAI
    respuesta, threadId = ejecutar_agente(texto)
    requests.post(WHAPI_URL, headers={
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "accept": "application/json",
        "Content-Type": "application/json"
    }, json={"to": numero_id, "body": respuesta})
    requests.post("https://www.bsl.com.co/_functions/guardarConversacion", json={
        "userId": numero_id,
        "nombre": "sistema",
        "mensajes": [{"from": "sistema", "mensaje": respuesta}],
        "threadId": threadId
    })
    return jsonify({"status": "ok", "respuesta": respuesta}), 200

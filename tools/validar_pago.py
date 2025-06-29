import requests
import os
import openai
from tools.pdf_sender import generar_pdf, send_pdf

openai.api_key = os.getenv("OPENAI_API_KEY")
WHAPI_KEY = os.getenv("WHAPI_TOKEN")

def send_text_message(to, body):
    resp = requests.post(
        "https://gate.whapi.cloud/messages/text",
        headers={
            "Authorization": f"Bearer {WHAPI_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "to": to,
            "body": body
        }
    )
    print("📤 Respuesta Whapi (historial):", resp.status_code, resp.text)

def run(imagen_url, numeroId=None, whatsapp_id=None, thread_id=None):
    print(f"🪝 thread_id recibido en validar_pago.run: {thread_id!r}")
    # Paso 1: analizar si la imagen es un comprobante de pago real
    prompt_analisis = (
        "Observa la imagen adjunta de un comprobante bancario.\n"
        "Responde solo 'sí' si es un comprobante real de pago, o 'no' si NO lo es. "
        "No expliques nada, responde solo sí o no."
    )

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_analisis},
                    {"type": "image_url", "image_url": {"url": imagen_url}}
                ]
            }],
            max_tokens=3
        )
        decision = response.choices[0].message.content.strip().lower()
    except Exception as e:
        print("❌ Error OpenAI comprobante:", e)
        return "Ocurrió un error analizando la imagen. Intenta de nuevo."

    if numeroId is None or whatsapp_id is None:
        # Solo validar si la imagen es comprobante. Si sí, pide documento.
        if "sí" in decision or "si" in decision:
            return "✅ El comprobante parece válido. Por favor, dime tu número de documento para registrarlo."
        else:
            return "⚠️ La imagen no parece un comprobante válido. Por favor, envía una foto clara del comprobante de pago."

    # Paso 2: extraer y validar el valor pagado
    prompt_valor = (
        "Extrae SOLO el valor pagado en pesos colombianos que aparece en el comprobante adjunto. "
        "Responde solo con el número, sin símbolos, ni puntos, ni texto adicional. Ejemplo: 46000"
    )

    try:
        valor_response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_valor},
                    {"type": "image_url", "image_url": {"url": imagen_url}}
                ]
            }],
            max_tokens=10
        )
        valor = valor_response.choices[0].message.content.strip()
        valor = ''.join(filter(str.isdigit, valor))  # asegura solo dígitos
        print(f"💰 Valor detectado: {valor}")
    except Exception as e:
        print("❌ Error OpenAI valor:", e)
        return "Ocurrió un error extrayendo el valor del comprobante. Intenta con otra imagen."

    try:
        valor_int = int(valor)
        if valor_int >= 4600:
            # Marcar como pagado en Wix
            res = requests.post("https://www.bsl.com.co/_functions/marcarPagado", json={
                "userId": numeroId,
                "observaciones": "Pagado"
            })
            print(f"✅ Marcado como pagado: {res.status_code}")

            # Generar y enviar PDF solo si marcó exitosamente como pagado
            try:
                pdf_url = generar_pdf(numeroId)
                send_pdf(whatsapp_id, pdf_url)

            except Exception as e:
                print("❌ Error generando/enviando PDF:", e)
                return f"El pago se registró pero hubo un error generando el certificado: {str(e)}"

        else:
            return f"El valor detectado (${valor_int}) es menor al esperado. Por favor revisa el comprobante."
    except Exception as e:
        print("❌ Error extrayendo el valor como número:", e)
        return "No pude identificar claramente el valor en el comprobante. Intenta con una imagen más clara."

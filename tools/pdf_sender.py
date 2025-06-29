import os
import requests

WHAPI_KEY = os.getenv("WHAPI_TOKEN")
API2PDF_KEY = os.getenv("API2PDF_KEY")

def marcar_pagado(user_id):
    try:
        resp = requests.post("https://www.bsl.com.co/_functions/marcarPagado", json={
            "userId": user_id,
            "observaciones": "Pagado"
        })
        print("✅ Marcado como pagado:", resp.status_code)
    except Exception as e:
        print("❌ Error marcando como pagado:", e)

def generar_pdf(documento):
    api_endpoint = 'https://v2018.api2pdf.com/chrome/url'
    url = f'https://www.bsl.com.co/descarga-whp/{documento}'
    print(f"📝 Generando PDF desde URL: {url}")

    response = requests.post(api_endpoint, headers={
        "Content-Type": "application/json",
        "Authorization": API2PDF_KEY
    }, json={
        "url": url,
        "inlinePdf": False,
        "fileName": f"{documento}.pdf"
    })

    result = response.json()
    print("📝 Respuesta API2PDF:", result)
    if not result.get("success"):
        raise Exception(result.get("error", "Error generando PDF"))
    
    pdf_url = result["pdf"]
    print("🔗 PDF generado en:", pdf_url)
    return pdf_url

def send_pdf(to, pdf_url):
    print("📨 Enviando PDF a:", to)
    print("🔗 URL del PDF a enviar:", pdf_url)
    body = {
        "to": to,
        "media": pdf_url,
        "caption": "Aquí tienes tu certificado médico en PDF."
    }

    resp = requests.post("https://gate.whapi.cloud/messages/document", headers={
        "Authorization": f"Bearer {WHAPI_KEY}",
        "Content-Type": "application/json"
    }, json=body)

    print("📤 Respuesta Whapi:", resp.status_code, resp.text)

    try:
        data = resp.json()
        if resp.status_code == 200 and data.get("messages"):
            print("✅ PDF enviado correctamente a WhatsApp")
            return True
        else:
            print("❌ No se pudo enviar el PDF:", data)
            return False
    except Exception as e:
        print("❌ Error procesando respuesta Whapi:", e)
        return False

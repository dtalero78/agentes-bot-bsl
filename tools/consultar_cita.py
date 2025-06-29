# tools/consultar_cita.py
import requests

def run(numero_id: str) -> str:
    url = f"https://www.bsl.com.co/_functions/informacionPaciente?numeroId={numero_id}"

    try:
        print(f"🔎 Consultando URL: {url}")
        response = requests.get(url, timeout=10)
        data = response.json()
        print(f"📦 Respuesta de Wix: {data}")

        if not data or not data.get("informacion"):
            return f"❌ No se encontró ninguna cita asociada a tu número de documento {numero_id}."

        item = data["informacion"][0]
        fecha_completa = item.get("fechaAtencion")

        if fecha_completa:
            from datetime import datetime
            fecha = datetime.fromisoformat(fecha_completa.replace("Z", "")).strftime("%Y-%m-%d")
            hora = datetime.fromisoformat(fecha_completa.replace("Z", "")).strftime("%H:%M")
            return f"✅ Tienes una cita programada para el {fecha} a las {hora}."
        else:
            return f"🕐 Se encontró un registro, pero falta información de la fecha de atención."

    except Exception as e:
        print(f"❌ Error en la solicitud: {str(e)}")
        return f"⚠️ Error al consultar la cita: {str(e)}"

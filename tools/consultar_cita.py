# tools/consultar_cita.py
import requests
from datetime import datetime
import pytz  # Asegúrate de tenerlo instalado: pip install pytz

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
            # Parsear fecha en UTC y convertir a Colombia
            try:
                # Compatibilidad: quitar 'Z' si viene
                if fecha_completa.endswith("Z"):
                    fecha_completa = fecha_completa.replace("Z", "+00:00")
                dt_utc = datetime.fromisoformat(fecha_completa)
                dt_col = dt_utc.astimezone(pytz.timezone("America/Bogota"))
                fecha = dt_col.strftime("%Y-%m-%d")
                hora = dt_col.strftime("%H:%M")
                return f"✅ Tienes una cita programada para el {fecha} a las {hora}."
            except Exception as ee:
                print(f"❌ Error parseando la fecha: {ee}")
                return f"🕐 Se encontró un registro pero hubo error con la fecha: {ee}"

        else:
            return f"🕐 Se encontró un registro, pero falta información de la fecha de atención."

    except Exception as e:
        print(f"❌ Error en la solicitud: {str(e)}")
        return f"⚠️ Error al consultar la cita: {str(e)}"

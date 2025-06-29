import requests
import base64
import os

def upload_image_to_imgbb(img_data):
    api_key = os.getenv("IMGBB_API_KEY")
    if not api_key:
        print("❌ IMGBB_API_KEY no configurado")
        raise Exception("IMGBB_API_KEY no configurado")
    
    # img_data debe ser binario, NO base64 ni string ni dataURL
    # Si quieres debuggear:
    print("ℹ️ img_data type:", type(img_data), "len:", len(img_data))

    b64_img = base64.b64encode(img_data).decode("utf-8")
    payload = {"image": b64_img}

    url = f"https://api.imgbb.com/1/upload?key={api_key}"
    resp = requests.post(url, data=payload)
    print("🔍 Respuesta cruda de imgbb:", resp.status_code, resp.text)
    resp.raise_for_status()
    result = resp.json()
    if not result.get("success", False):
        error_msg = result.get("error", {}).get("message", "Error desconocido")
        print("❌ Error de imgbb:", error_msg)
        raise Exception(f"Error imgbb: {error_msg}")
    print("✅ Imagen subida correctamente a imgbb:", result["data"]["url"])
    return result["data"]["url"]

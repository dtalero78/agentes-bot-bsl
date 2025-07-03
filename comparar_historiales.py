import openai
import requests
from dotenv import load_dotenv
import os

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def obtener_historial_wix(user_id):
    """Ajusta la URL/endpoint para tu entorno"""
    url = f"https://www.bsl.com.co/_functions/obtenerConversacion?userId={user_id}"
    res = requests.get(url)
    res.raise_for_status()
    data = res.json() or {}
    # Ajusta si la estructura es diferente
    return data.get("mensajes", [])

def obtener_historial_openai(thread_id):
    """Devuelve lista de dicts: [{"role": ..., "content": ...}]"""
    messages = openai.beta.threads.messages.list(thread_id=thread_id)
    historial_openai = []
    for m in reversed(messages.data):  # reversed para orden cronológico
        rol = m.role
        if m.content:
            text = m.content[0].text.value if hasattr(m.content[0], "text") else str(m.content[0])
        else:
            text = ""
        historial_openai.append({"role": rol, "content": text})
    return historial_openai

def compara_historiales(user_id, thread_id):
    wix = obtener_historial_wix(user_id)
    openai_h = obtener_historial_openai(thread_id)
    print("---- HISTORIAL WIX ----")
    for i, m in enumerate(wix):
        print(f"{i+1:02d}. {m['from']}: {m['mensaje']}")
    print("\n---- HISTORIAL OPENAI ----")
    for i, m in enumerate(openai_h):
        print(f"{i+1:02d}. {m['role']}: {m['content']}")
    print("\n---- DIFERENCIAS ----")
    # Muestra diferencias simples: por cantidad y por contenido
    min_len = min(len(wix), len(openai_h))
    for i in range(min_len):
        wix_msg = wix[i]['mensaje'].strip()
        openai_msg = openai_h[i]['content'].strip()
        if wix_msg != openai_msg:
            print(f"✗ Diferencia en posición {i+1}:")
            print(f"  Wix:    {wix_msg}")
            print(f"  OpenAI: {openai_msg}")
    if len(wix) != len(openai_h):
        print(f"✗ Cantidad de mensajes diferente: Wix={len(wix)}, OpenAI={len(openai_h)}")
        if len(wix) > len(openai_h):
            print("Wix tiene mensajes que nunca llegaron a OpenAI.")
        else:
            print("OpenAI tiene mensajes que no están en Wix (raro).")

# USO:
if __name__ == "__main__":
    # Pega aquí el user_id y el thread_id que quieres comparar
    user_id = "573217521967"
    thread_id = "thread_UKENfwMk4CxLtDgecTcuTKNx"
    compara_historiales(user_id, thread_id)

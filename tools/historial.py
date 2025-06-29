import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def obtener_historial(thread_id, max_mensajes=50):
    try:
        historial = []
        # Pide hasta max_mensajes, en orden cronológico (antiguos primero)
        response = openai.beta.threads.messages.list(
            thread_id=thread_id,
            limit=max_mensajes,
            order="asc"  # "asc" = antiguos primero
        )
        for m in response.data:
            rol = m.role
            contenido = m.content[0].text.value if m.content else "[sin contenido]"
            historial.append(f"{rol.upper()}: {contenido}")
        return "\n".join(historial)
    except Exception as e:
        print("❌ Error al obtener historial:", e)
        return "No se pudo recuperar el historial de conversación."

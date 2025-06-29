import openai

def obtener_historial(thread_id):
    try:
        messages = openai.beta.threads.messages.list(thread_id=thread_id)

        historial = []
        for m in reversed(messages.data):  # Orden cronológico
            rol = m.role
            contenido = m.content[0].text.value if m.content else "[sin contenido]"
            historial.append(f"{rol.upper()}: {contenido}")

        return "\n".join(historial)

    except Exception as e:
        print("❌ Error al obtener historial:", e)
        return "No se pudo recuperar el historial de conversación."

import os
import time
import openai
from dotenv import load_dotenv

import tools.generar_certificado as generar_certificado
import tools.validar_pago as validar_pago
import tools.consultar_cita as consultar_cita

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")


def ejecutar_agente(texto_usuario, thread_id=None, imagen_url=None):
    # 1. Crear thread si no existe
    if not thread_id:
        thread = openai.beta.threads.create()
        thread_id = thread.id

    # 2. Agrega el mensaje del usuario
    if imagen_url:
        content = [
            {"type": "text", "text": texto_usuario},
            {"type": "image_url", "image_url": {"url": imagen_url}}
        ]
    else:
        content = texto_usuario

    openai.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=content
    )

    # 3. Ejecuta el asistente
    run = openai.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id="asst_Atmi3qOvdpd6vvfHoZ15ufSc"
    )

    if run.status == "completed":
        messages = openai.beta.threads.messages.list(thread_id=thread_id)

        print("🧵 HISTORIAL DE CONVERSACIÓN:")
        for m in reversed(messages.data):  # Mostrar en orden cronológico
            rol = m.role
            contenido = m.content[0].text.value if m.content else "[sin contenido]"
            print(f"{rol.upper()}: {contenido}")

        respuesta = messages.data[0].content[0].text.value
        return respuesta, thread_id

    elif run.status == "requires_action":
        for call in run.required_action.submit_tool_outputs.tool_calls:
            tool_name = call.function.name
            arguments = eval(call.function.arguments)

            if tool_name == "generar_certificado":
                resultado = generar_certificado.run(**arguments)
            elif tool_name == "validar_pago":
                resultado = validar_pago.run(**arguments)
            elif tool_name == "consultar_cita":
                resultado = consultar_cita.run(**arguments)
            else:
                resultado = "Esta función aún no está implementada."

            openai.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=[{
                    "tool_call_id": call.id,
                    "output": resultado
                }]
            )

        # Espera hasta que el run esté completo
        while True:
            run_check = openai.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run_check.status in ["completed", "failed", "cancelled"]:
                break
            time.sleep(1)

        messages = openai.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=1)

        print("🧵 HISTORIAL DE CONVERSACIÓN:")
        for m in reversed(messages.data):
            rol = m.role
            contenido = m.content[0].text.value if m.content else "[sin contenido]"
            print(f"{rol.upper()}: {contenido}")

        respuesta = messages.data[0].content[0].text.value
        return respuesta, thread_id

    else:
        return "Ocurrió un error con el agente.", thread_id

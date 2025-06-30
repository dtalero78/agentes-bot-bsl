import os
import time
import openai
from dotenv import load_dotenv

import tools.generar_certificado as generar_certificado
import tools.validar_pago as validar_pago
import tools.consultar_cita as consultar_cita

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def clasificar_documento(imagen_url: str) -> str:
    return "comprobante_pago"

def crear_thread_si_no_existe(thread_id=None):
    if not thread_id:
        thread = openai.beta.threads.create()
        return thread.id
    return thread_id

def ejecutar_agente(texto_usuario: str = "", thread_id: str = None, imagen_url: str = None):
    thread_id = crear_thread_si_no_existe(thread_id)

    if imagen_url:
        content = []
        if texto_usuario:
            content.append({"type": "text", "text": texto_usuario})
        content.append({"type": "image_url", "image_url": {"url": imagen_url}})
    else:
        content = texto_usuario or ""

    openai.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=content
    )

    run = openai.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id="asst_Atmi3qOvdpd6vvfHoZ15ufSc"
    )

    while run.status == "requires_action":
        tool_outputs = []
        for call in run.required_action.submit_tool_outputs.tool_calls:
            name = call.function.name
            args = eval(call.function.arguments)

            if name == "clasificar_documento":
                resultado = clasificar_documento(args["imagen_url"])
            elif name == "validar_pago":
                resultado = validar_pago.run(**args)
            elif name == "generar_certificado":
                resultado = generar_certificado.run(**args)
            elif name == "consultar_cita":
                resultado = consultar_cita.run(**args)
            else:
                resultado = "Función no implementada."

            tool_outputs.append({
                "tool_call_id": call.id,
                "output": resultado
            })

        openai.beta.threads.runs.submit_tool_outputs(
            thread_id=thread_id,
            run_id=run.id,
            tool_outputs=tool_outputs
        )

        while True:
            run = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if run.status in ["completed", "failed", "cancelled", "requires_action"]:
                break
            time.sleep(1)

    messages = openai.beta.threads.messages.list(thread_id=thread_id)
    if messages.data:
        last = messages.data[0].content[0].text.value if messages.data[0].content else ""
    else:
        last = ""
    return last, thread_id

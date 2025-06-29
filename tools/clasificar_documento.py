# tools/clasificar_documento.py
import openai
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def run(imagen_url: str) -> str:
    """
    Clasifica la imagen según su contenido.
    Devuelve uno de: comprobante_pago, examen_medico, documento_identidad, otro.
    """
    prompt = (
        "Te envío una imagen: clasifícala en UNA de estas categorías:\n"
        "  • comprobante_pago\n"
        "  • examen_medico\n"
        "  • documento_identidad\n"
        "  • otro\n"
        "Responde solo la etiqueta."
    )
    resp = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": prompt},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": imagen_url}}
            ]}
        ],
        max_tokens=1
    )
    return resp.choices[0].message.content.strip().lower()

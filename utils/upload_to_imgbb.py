# utils/upload_to_imgbb.py
import requests
import base64
import os

def upload_image_to_imgbb(img_data):
    api_key = os.getenv("IMGBB_API_KEY")
    b64_img = base64.b64encode(img_data).decode("utf-8")
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data={
            "key": api_key,
            "image": b64_img
        }
    )
    resp.raise_for_status()
    url = resp.json()["data"]["url"]
    return url

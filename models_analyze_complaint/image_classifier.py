import os
import requests

HF_TOKEN = os.getenv("HF_TOKEN")
# Using the CLIP model via API
API_URL = "https://api-inference.huggingface.co/models/openai/clip-vit-base-patch32"

def classify_image(image_bytes, labels):
    if not HF_TOKEN:
        return "Error: No Token"
    
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {
        "inputs": image_bytes.decode('ISO-8859-1') if isinstance(image_bytes, bytes) else image_bytes,
        "parameters": {"candidate_labels": labels}
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=20)
        return response.json()
    except:
        return []

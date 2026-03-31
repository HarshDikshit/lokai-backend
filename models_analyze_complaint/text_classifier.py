import os
import requests

HF_TOKEN = os.getenv("HF_TOKEN")
# Standard Zero-Shot Classification model
API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"

labels = [
    "Infrastructure & Roads",
    "Sanitation & Waste",
    "Water Supply",
    "Electricity",
    "Public Safety",
    "Healthcare",
    "Education",
    "Transportation",
    "Environment",
    "Government Services"
]

def classify_text(text):
    if not HF_TOKEN:
        return "Error: No Token"

    headers = {{"Authorization": f"Bearer {HF_TOKEN}"}}
    payload = {{
        "inputs": text,
        "parameters": {{"candidate_labels": labels}}
    }}

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=20)
        result = response.json()
        # Return the top label
        if 'labels' in result and len(result['labels']) > 0:
            return result['labels'][0]
    except:
        pass
    return "Uncategorized"

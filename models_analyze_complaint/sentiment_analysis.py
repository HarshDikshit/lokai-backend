import os
import requests

HF_TOKEN = os.getenv("HF_TOKEN")
API_URL = "https://api-inference.huggingface.co/models/distilbert-base-uncased-finetuned-sst-2-english"

def analyze_sentiment(text):
    if not HF_TOKEN:
        return {"label": "NEUTRAL", "score": 0.0}
    
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": text}
    
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=10)
        result = response.json()
        if isinstance(result, list) and len(result) > 0:
            res = result[0][0]
            return {"label": res["label"], "score": res["score"]}
    except:
        pass
    return {"label": "ERROR", "score": 0.0}

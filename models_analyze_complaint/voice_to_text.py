import os
import requests

HF_TOKEN = os.getenv("HF_TOKEN")
API_URL = "https://api-inference.huggingface.co/models/openai/whisper-base"

def transcribe_audio(audio_path):
    if not HF_TOKEN:
        return "Error: No Token"

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    try:
        with open(audio_path, "rb") as f:
            data = f.read()
        response = requests.post(API_URL, headers=headers, data=data, timeout=30)
        result = response.json()
        return result.get("text", "")
    except Exception as e:
        return f"Transcription Error: {str(e)}"

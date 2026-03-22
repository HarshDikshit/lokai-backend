import os
import re
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database.connection import get_database

router = APIRouter()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "sk_nisznd9t_ipWfE1Y8D5HvaHAAMFgqkspk")

class ChatRequest(BaseModel):
    message: str

SYSTEM_PROMPT = """
You are LokAI Assistant.
STRICT RULES:
- Answer in maximum 2–3 lines ONLY
- Be direct and practical
- Do NOT include explanations, reasoning, or thinking
- Do NOT assume anything not given
- Do NOT mention downloading app or external steps
APP FLOW (IMPORTANT):
- Submit issue → 'Submit Issue' section
- Track issue → 'My Issues' section
- Users already logged into app
YOUR JOB:
- Guide users inside the app
- Give short, realistic steps
STYLE:
- Simple, Clear, Helpful
"""

def detect_language(text):
    url = "https://api.sarvam.ai/v1/language-detection"
    headers = {"Authorization": f"Bearer {SARVAM_API_KEY}", "Content-Type": "application/json"}
    try:
        res = requests.post(url, json={"input": text}, headers=headers)
        return res.json().get("language_code", "en-IN")
    except:
        return "en-IN"

def translate_text(text, source_lang, target_lang):
    if source_lang == target_lang: return text
    url = "https://api.sarvam.ai/v1/translate"
    headers = {"Authorization": f"Bearer {SARVAM_API_KEY}", "Content-Type": "application/json"}
    payload = {"input": text, "source_language_code": source_lang, "target_language_code": target_lang}
    try:
        res = requests.post(url, json=payload, headers=headers)
        return res.json().get("translated_text", text)
    except:
        return text

def detect_intent(text):
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {SARVAM_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "sarvam-m",
        "messages": [
            {"role": "system", "content": "Classify intent into: general_query or issue_status. Only return one word."},
            {"role": "user", "content": text}
        ]
    }
    try:
        res = requests.post(url, json=payload, headers=headers)
        return res.json()["choices"][0]["message"]["content"].strip().lower()
    except:
        return "general_query"

def clean_response(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.replace('"', '').replace('\n', ' ')
    text = re.sub(r"\b\d+\.\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()

def generate_ai_response(text):
    url = "https://api.sarvam.ai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {SARVAM_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "sarvam-m",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
    }
    try:
        res = requests.post(url, json=payload, headers=headers)
        raw_output = res.json()["choices"][0]["message"]["content"]
        return clean_response(raw_output)
    except:
        return "I am having trouble processing that right now."

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    db = get_database()
    orig_lang = detect_language(request.message)
    eng_text = translate_text(request.message, orig_lang, "en-IN")
    intent = detect_intent(eng_text)
    if "issue" in intent:
        latest_issue = await db.issues.find_one(sort=[("created_at", -1)])
        if latest_issue:
            response_text = f"Your latest issue regarding {latest_issue.get('category')} is currently {latest_issue.get('status', 'Pending')}."
        else:
            response_text = "No issues found for your account."
    else:
        response_text = generate_ai_response(eng_text)
    final_response = translate_text(response_text, "en-IN", orig_lang)
    return {"response": final_response, "original_language": orig_lang}
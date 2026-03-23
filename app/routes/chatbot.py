import os
import re
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database.connection import get_database


router = APIRouter(prefix='/chatbot', tags=['chatbot'])

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "sk_nisznd9t_ipWfE1Y8D5HvaHAAMFgqkspk")

class ChatRequest(BaseModel):
    message: str

SYSTEM_PROMPT = """
You are LokAI Assistant.

STRICT RULES:
- Answer in maximum 2–3 lines ONLY
- Be direct, practical, and helpful
- No explanations, no reasoning
- No step numbering, no bullets
- No quotes, no \\n, no symbols

APP CONTEXT:
- User is already inside the app
- Submit issue → "Submit Issue"
- Track issue → "My Issues"

YOUR JOB:
1. Answer general app queries clearly
2. Help user navigate inside app
3. Give small practical civic advice when relevant

ADVICE RULES:
- Give only simple, safe, real-world suggestions
- Do NOT give technical or risky instructions
- Keep advice short (1 line max)

EXAMPLES:

User: how to report issue
Answer: Go to Submit Issue, fill details and submit your complaint.

User: garbage problem in my area
Answer: Report it from Submit Issue with a clear photo and exact location for faster action.

User: how to check status
Answer: Open My Issues section to track your complaint updates.

User: water leakage problem
Answer: Report it with proper location and description so authorities can act quickly.

STYLE:
- Simple
- Clear
- Human-like
- No extra text

"""


def format_issue_status(issue):
    status = issue.get("status", "").upper()

    if status == "OPEN":
        return "Your issue is registered and awaiting action."

    elif status == "IN_PROGRESS":
        return "Your issue is currently being worked on."

    elif status == "RESOLVED_L1":
        return "Your issue has been resolved by the authority."

    elif status == "CLOSED":
        return "Your issue has been successfully closed."

    else:
        return "Your issue status is currently unavailable."



def detect_language(text):
    url = "https://api.sarvam.ai/v1/language-detection"

    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "input": text
    }

    res = requests.post(url, json=payload, headers=headers)
    data = res.json()
    print("RAW LANGUAGE DETECTION RESPONSE:", data)
    return data.get("language_code", "en")



def translate_text(text, source_lang, target_lang):
    if source_lang == target_lang:
        return text

    url = "https://api.sarvam.ai/v1/translate"

    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "input": text,
        "source_language_code": source_lang,
        "target_language_code": target_lang
    }

    res = requests.post(url, json=payload, headers=headers)
    data = res.json()
    print("TRANSLATION API RESPONSE:", data)
    return data.get("translated_text", text)



def detect_intent(text):
    url = "https://api.sarvam.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "sarvam-m",
        "messages": [
            {
                "role": "system",
                "content": """You are an intent classifier. Classify the user message into ONLY one of these two intents:

issue_status → ONLY when the user is explicitly asking about the status/update of an already submitted complaint AND provides a complaint ID (a long code like 69ba2ed5ed8e612d6434aa64).

general_query → Everything else. This includes:
- Reporting a new problem (pothole, garbage, fire, water, etc.)
- Asking how to use the app
- Asking for advice or help
- Any civic complaint or emergency without an ID

RULE: If there is NO complaint ID in the message, ALWAYS return general_query.

Return ONLY one word: general_query or issue_status. No explanation."""
            },
            {
                "role": "user",
                "content": text
            }
        ]
    }

    res = requests.post(url, json=payload, headers=headers)
    data = res.json()

    raw = data["choices"][0]["message"]["content"]

    return clean_intent(raw)



def clean_intent(text):
    # Remove <think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    # Remove spaces/newlines
    text = text.strip().lower()

    return text


def clean_response(text):
    try:
        text = ast.literal_eval(text)
    except:
        pass

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    text = text.replace('\"', '')

    text = text.replace('\n', ' ')

    text = re.sub(r"\b\d+\.\s*", "", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ✅ LIMIT TO 3 LINES (extra safety)
def limit_lines(text, max_lines=3):
    lines = text.split("\n")
    return "\n".join(lines[:max_lines])



def generate_response(text):
    url = "https://api.sarvam.ai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {SARVAM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "sarvam-m",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ]
    }

    res = requests.post(url, json=payload, headers=headers)
    data = res.json()

    raw_output = data["choices"][0]["message"]["content"]

    # ✅ CLEAN + LIMIT OUTPUT
    cleaned = clean_response(raw_output)
    final = limit_lines(cleaned)

    return final

def extract_object_id(text):
    # Normalize text
    text = text.lower()

    # Find all 24-length hex strings
    matches = re.findall(r"[a-f0-9]{24}", text)

    if matches:
        return matches[0]

    return None

@router.post("/chat")
async def chat(req: ChatRequest):
    user_msg = req.message
    db = get_database()

    lang = detect_language(user_msg)
    english_msg = translate_text(user_msg, lang, "en")

    intent = detect_intent(english_msg)

    if "issue_status" in intent.lower():

        match = re.findall(r"[a-fA-F0-9]{24}", user_msg)
        issue_id = match[0] if match else None

        if not issue_id:
            response_text = "Please provide a valid issue ID."
        else:
            try:
                # ✅ No await - sync call
                issue = db.issues.find_one({"_id": ObjectId(issue_id)})

                if issue:
                    response_text = format_issue_status(issue)
                else:
                    response_text = "Issue not found in database."

            except Exception as e:
                import traceback
                print("FULL TRACEBACK:\n", traceback.format_exc())
                response_text = f"Error: {str(e)}"
    else:
        response_text = generate_response(english_msg)
    

    final_response = translate_text(response_text, "en", lang)
    return {
        "intent": intent,
        "response": final_response
    }

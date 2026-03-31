from fastapi import APIRouter
from newsapi import NewsApiClient
import re
import os
import requests

router = APIRouter(prefix='/social-media', tags=['Social Media Analysis'])

# -------------------------
# CONFIG
# -------------------------

# Use HF Inference API for sentiment
HF_TOKEN = os.getenv('HF_TOKEN')
SENTIMENT_API_URL = 'https://api-inference.huggingface.co/models/distilbert-base-uncased-finetuned-sst-2-english'

newsapi = NewsApiClient(api_key="b9810b2643334398acef16112382779e")

def analyze_sentiment_api(text):
    if not HF_TOKEN: return {'label': 'NEUTRAL', 'score': 0.0}
    headers = {'Authorization': f'Bearer {HF_TOKEN}'}
    try:
        response = requests.post(SENTIMENT_API_URL, headers=headers, json={'inputs': text}, timeout=10)
        result = response.json()
        if isinstance(result, list) and len(result) > 0:
            return result[0][0]
    except:
        pass
    return {'label': 'ERROR', 'score': 0.0}

@router.get("/trending")
async def get_trending_issues():
    # Example search for civic issues
    try:
        articles = newsapi.get_everything(
            q="civic issues india",
            language="en",
            sort_by="relevancy",
            page_size=10
        )
        
        results = []
        for art in articles.get('articles', []):
            sentiment = analyze_sentiment_api(art.get('description', ''))
            results.append({
                "title": art.get('title'),
                "url": art.get('url'),
                "sentiment": sentiment
            })
        return {"status": "success", "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}

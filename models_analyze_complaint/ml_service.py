import httpx
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

ML_API_BASE_URL = os.getenv("ML_API_BASE_URL", "http://localhost:8001")


async def analyze_issue(title: str, description: str) -> dict:
    """Call external ML API to get category, urgency_score, priority_score."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{ML_API_BASE_URL}/ml/analyze-issue",
                json={"title": title, "description": description}
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"ML API error (analyze-issue): {e}")
    
    # Fallback defaults if ML API unavailable
    return {
        "category": "General",
        "urgency_score": 0.5,
        "priority_score": 0.5
    }


async def analyze_sentiment(comments: list) -> dict:
    """Call external ML API to get sentiment analysis."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{ML_API_BASE_URL}/ml/sentiment",
                json={"comments": comments}
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"ML API error (sentiment): {e}")
    
    # Fallback defaults
    return {
        "positive": 0.33,
        "negative": 0.33,
        "neutral": 0.34
    }


def score_to_urgency(score: float) -> str:
    if score >= 0.8:
        return "critical"
    elif score >= 0.6:
        return "high"
    elif score >= 0.4:
        return "medium"
    return "low"
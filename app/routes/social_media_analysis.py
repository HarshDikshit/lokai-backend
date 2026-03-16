from fastapi import APIRouter
from newsapi import NewsApiClient
from transformers import pipeline
import re

router = APIRouter(prefix="/social-media", tags=["Social Media Analysis"])

# -------------------------
# CONFIG
# -------------------------

newsapi = NewsApiClient(api_key="0738ed98bd3e465aa322574163ab769b")

sentiment_model = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)

keywords = [
    "road pothole india",
    "garbage problem india",
    "water shortage india",
    "electricity outage india",
    "traffic issue india",
    "drainage problem india",
    "city pollution india",
    "LPG shortage in India",
    "Pollution issue in India",
    "Environmental issues in India",
    "corruption issue in India",
    "sewer blockage in India",
    "littering problem in India",
    "women safety issues in India",
    "healthcare issues in India",
    "hospitals not working in India"
]

# -------------------------
# CLEAN TEXT
# -------------------------

def clean_text(text):

    text = text.lower()
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"[^a-zA-Z\s]", "", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# -------------------------
# CIVIC KEYWORDS
# -------------------------

civic_keywords = [
    "pothole","garbage","road","traffic","water",
    "electricity","drainage","flood","sewage",
    "pollution","shortage","gas","lpg","accident",
    "fire","damage","crisis","open dumping",
    "public transport","power cuts","littering",
    "stray animal","illegal","leakage","plastic",
    "air quality"
]


def contains_civic_issue(text):

    for word in civic_keywords:

        pattern = r"\b" + re.escape(word) + r"\b"

        if re.search(pattern, text):

            return True

    return False


# -------------------------
# ISSUE CATEGORIES
# -------------------------

issue_categories = {

    "Infrastructure & Roads":[
        "pothole","road","traffic","accident","damage"
    ],

    "Sanitation & Waste":[
        "garbage","littering","open dumping","sewage"
    ],

    "Water Supply":[
        "water","drainage","leakage","flood"
    ],

    "Electricity":[
        "electricity","power cuts"
    ],

    "Public Safety":[
        "fire","illegal","stray animal"
    ],

    "Healthcare":[
        "hospital","medical","healthcare"
    ],

    "Transportation":[
        "public transport","traffic"
    ],

    "Environment":[
        "pollution","plastic","air quality"
    ],

    "Government Services":[
        "gas","lpg","shortage","crisis"
    ]
}


def detect_issue_category(text):

    for category, keys in issue_categories.items():

        for keyword in keys:

            pattern = r"\b" + re.escape(keyword) + r"\b"

            if re.search(pattern, text):

                return category

    return "Other"


# -------------------------
# SENTIMENT
# -------------------------

def get_sentiment(text):

    result = sentiment_model(text[:512])[0]

    return result["label"]


# -------------------------
# API ROUTE
# -------------------------

@router.get("/social-monitor")

def social_monitor():

    posts = []

    for key in keywords:

        articles = newsapi.get_everything(
            q=key,
            language="en",
            page_size=10
        )

        for article in articles["articles"]:

            title = article["title"] or ""
            summary = article["description"] or ""

            text = clean_text(title + " " + summary)

            if contains_civic_issue(text):

                sentiment = get_sentiment(text)

                category = detect_issue_category(text)

                posts.append({

                    "title": title,
                    "summary": summary,
                    "sentiment": sentiment,
                    "issue_category": category

                })

    # -------------------------
    # TREND DETECTION
    # -------------------------

    trend_counts = {}

    for post in posts:

        category = post["issue_category"]

        if category not in trend_counts:
            trend_counts[category] = 0

        trend_counts[category] += 1


    # -------------------------
    # RESPONSE
    # -------------------------

    return {

        "total_posts": len(posts),

        "trending_issues": trend_counts,

        "posts": posts

    }
from transformers import pipeline

sentiment_analyzer = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english",
    device=-1
)

def analyze_sentiment(text):

    result = sentiment_analyzer(text)[0]

    label = result["label"]
    confidence = result["score"]

    if label == "NEGATIVE":
        sentiment_score = -confidence
    else:
        sentiment_score = confidence

    return {
        "sentiment_label": label,
        "sentiment_confidence": round(confidence,3),
        "sentiment_score": round(sentiment_score,3)
    }
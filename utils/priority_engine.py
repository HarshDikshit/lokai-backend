def calculate_priority(category, sentiment_score, confidence, text, frequency):

    base_weights = {
        "Public Safety": 0.9,
        "Healthcare": 0.85,
        "Transportation": 0.8,
        "Infrastructure & Roads": 0.75,
        "Water Supply": 0.7,
        "Environment": 0.65
    }

    base = base_weights.get(category, 0.6)

    sentiment_weight = abs(sentiment_score) * 0.05
    confidence_weight = confidence * 0.05
    frequency_weight = min(frequency * 0.03, 0.1)

    priority = base + sentiment_weight + confidence_weight + frequency_weight

    return min(priority, 0.95)
from models_analyze_complaint.text_classifier import classify_text
from models_analyze_complaint.sentiment_analysis import analyze_sentiment
from models_analyze_complaint.voice_to_text import transcribe_audio
from models_analyze_complaint.image_classifier import classify_image

from utils.fusion import fuse_modalities
from utils.priority_engine import calculate_priority

category_frequency = {}

def process_complaint(text=None, voice_path=None, image_path=None):

    processed_text = text
    text_result = None
    image_result = None
    sentiment_result = None

    if voice_path:
        processed_text = transcribe_audio(voice_path)

    if processed_text:
        text_result = classify_text(processed_text)
        sentiment_result = analyze_sentiment(processed_text)

    if image_path:
        image_result = classify_image(image_path)

    fusion_result = fuse_modalities(text_result, image_result)

    final_category = fusion_result["final_category"]
    final_confidence = fusion_result["final_confidence"]

    if final_category not in category_frequency:
        category_frequency[final_category] = 0

    category_frequency[final_category] += 1
    frequency_count = category_frequency[final_category]

    sentiment_score = sentiment_result["sentiment_score"] if sentiment_result else 0

    priority_score = calculate_priority(
        final_category,
        sentiment_score,
        final_confidence,
        processed_text,
        frequency_count
    )

    return {
        "category": final_category,
        "priority_score": round(priority_score,3)
    }

def run_pipeline(text=None, voice_path=None, image_path=None):
    return process_complaint(text, voice_path, image_path)
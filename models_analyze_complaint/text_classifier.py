from transformers import pipeline

labels = [
    "Infrastructure & Roads",
    "Sanitation & Waste",
    "Water Supply",
    "Electricity",
    "Public Safety",
    "Healthcare",
    "Education",
    "Transportation",
    "Environment",
    "Government Services"
]

classifier = pipeline(
    "zero-shot-classification",
    model="facebook/bart-large-mnli",
    device=-1
)

def classify_text(user_text):

    result = classifier(user_text, labels)

    return {
        "predicted_category": result["labels"][0],
        "confidence": round(result["scores"][0], 3)
    }
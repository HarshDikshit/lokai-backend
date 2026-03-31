from transformers import pipeline

image_classifier = pipeline(
    "zero-shot-image-classification",
    model="openai/clip-vit-base-patch32"
)

image_labels = [
    "Garbage pile",
    "Road damage or pothole",
    "Water leakage or flood",
    "Electric pole damage",
    "Fire accident",
    "Medical emergency",
    "Public protest",
    "Traffic accident",
    "Collapsed building"
]

def map_image_to_category(label):

    mapping = {
        "Garbage pile": "Sanitation & Waste",
        "Road damage or pothole": "Infrastructure & Roads",
        "Water leakage or flood": "Water Supply",
        "Electric pole damage": "Electricity",
        "Fire accident": "Public Safety",
        "Medical emergency": "Healthcare",
        "Public protest": "Public Safety",
        "Traffic accident": "Transportation",
        "Collapsed building": "Public Safety"
    }

    return mapping.get(label, "Government Services")


def classify_image(image_path):

    result = image_classifier(image_path, candidate_labels=image_labels)

    top_label = result[0]["label"]
    top_score = result[0]["score"]

    return {
        "mapped_category": map_image_to_category(top_label),
        "image_confidence": round(top_score,3)
    }
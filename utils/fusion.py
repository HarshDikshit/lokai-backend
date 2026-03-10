def fuse_modalities(text_result=None, image_result=None):

    if text_result and not image_result:
        return {
            "final_category": text_result["predicted_category"],
            "final_confidence": text_result["confidence"]
        }

    if image_result and not text_result:
        return {
            "final_category": image_result["mapped_category"],
            "final_confidence": image_result["image_confidence"]
        }

    if text_result and image_result:

        if text_result["predicted_category"] == image_result["mapped_category"]:
            return {
                "final_category": text_result["predicted_category"],
                "final_confidence": max(
                    text_result["confidence"],
                    image_result["image_confidence"]
                )
            }

        if text_result["confidence"] > image_result["image_confidence"]:
            return {
                "final_category": text_result["predicted_category"],
                "final_confidence": text_result["confidence"]
            }

        return {
            "final_category": image_result["mapped_category"],
            "final_confidence": image_result["image_confidence"]
        }

    return {"final_category": "Unknown", "final_confidence": 0.5}
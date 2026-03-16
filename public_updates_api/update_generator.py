# from transformers import pipeline

# # Load LLM
# generator = pipeline(
#     "text2text-generation",
#     model="google/flan-t5-large"
# )


# def determine_priority_label(priority_score):

#     if priority_score >= 0.85:
#         return "Critical"
#     elif priority_score >= 0.7:
#         return "High"
#     elif priority_score >= 0.5:
#         return "Medium"
#     else:
#         return "Low"


# def generate_ai_reasoning(category, sentiment, priority_score):

#         reasoning = f"""
#     The complaint has been classified under the category '{category}'.
#     Sentiment analysis detected a {sentiment.lower()} sentiment in the citizen report.
    
#     Based on the category relevance and sentiment intensity,
#     the system assigned a priority score of {round(priority_score,2)},
#     indicating {'high urgency' if priority_score >= 0.7 else 'moderate urgency'}.
    
#     This prioritization helps municipal authorities respond efficiently
#     to critical civic issues.
#     """

#         return reasoning.strip()

# def generate_llm_public_update(category, issue, location, priority_level, status):

#     if status == "acknowledged":

#         prompt = f"""
#     You are a municipal authority.
    
#     Write a short official acknowledgement update for citizens.
    
#     Issue: {issue}
#     Location: {location}
#     Category: {category}
    
#     Respond in one clear sentence stating that the issue has been identified
#     and authorities are working on it.
#     """

#     else:

#         prompt = f"""
#     You are a municipal authority.
    
#     Write a short resolution update for citizens.
    
#     Issue: {issue}
#     Location: {location}
#     Category: {category}
    
#     Respond in one sentence stating the issue has been resolved.
#     """

#     result = generator(prompt, max_length=60)

#     return result[0]["generated_text"].strip()
   
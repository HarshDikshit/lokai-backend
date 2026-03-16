# from fastapi import APIRouter
# from public_updates_api.schemas import UpdateRequest

# from public_updates_api.update_generator import (
#     determine_priority_label,
#     generate_ai_reasoning
# )

# router = APIRouter()


# @router.post("/generate-ai-reasoning")
# def ai_reasoning(data: UpdateRequest):

#     priority_label = determine_priority_label(data.priority_score)

#     reasoning = generate_ai_reasoning(
#         data.category,
#         data.sentiment,
#         data.priority_score
#     )

#     return {
#         "priority_level": priority_label,
#         "reasoning": reasoning
#     }

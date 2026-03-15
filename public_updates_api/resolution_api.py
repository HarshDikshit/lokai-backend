from fastapi import APIRouter
from schemas import UpdateRequest

from update_generator import (
    determine_priority_label,
    generate_ai_reasoning,
    generate_llm_public_update
)

router = APIRouter()


@router.post("/generate-resolution-update")

def resolution_update(data: UpdateRequest):

    priority_label = determine_priority_label(data.priority_score)

    reasoning = generate_ai_reasoning(
        data.category,
        data.sentiment,
        data.priority_score
    )

    update = generate_llm_public_update(
        data.category,
        data.issue,
        data.location,
        priority_label,
        "resolved"
    )

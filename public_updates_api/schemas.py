from pydantic import BaseModel

class UpdateRequest(BaseModel):

    category: str
    issue: str
    location: str
    priority_score: float
    sentiment: str
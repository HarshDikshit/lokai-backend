from fastapi import FastAPI

from public_updates_api.acknowledgement_api import router as ack_router
from public_updates_api.resolution_api import router as res_router
from public_updates_api.reasoning_api import router as reasoning_router

app = FastAPI(
    title="LokAI Public Communication API",
    description="Generate official public communication updates",
    version="1.0"
)

app.include_router(ack_router)
app.include_router(res_router)
app.include_router(reasoning_router)


@app.get("/")
def health_check():
    return {"message": "LokAI Public Communication API running"}    
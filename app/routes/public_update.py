# from fastapi import APIRouter, FastAPI

# from public_updates_api.acknowledgement_api import router as ack_router
# from public_updates_api.resolution_api import router as res_router
# from public_updates_api.reasoning_api import router as reasoning_router

# # router = APIRouter(prefix="/public-update", tags=["Public Update"])
# router = FastAPI()


# router.include_router(ack_router)
# router.include_router(res_router)
# router.include_router(reasoning_router)


# @router.get("/")
# def health_check():
#     return {"message": "LokAI Public Communication API running"}    
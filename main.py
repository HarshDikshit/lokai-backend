from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
from bson import ObjectId
from datetime import datetime
from starlette.responses import Response
import json
import os
from app.routes import feed

from app.database.connection import connect_to_mongo, close_mongo_connection
from app.routes import auth, issues, verifications, dashboard, analyze_complaint, social_media_analysis, public_update, chatbot


limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


# Create upload directories BEFORE app/static files are initialised
os.makedirs("uploads/images", exist_ok=True)
os.makedirs("uploads/audio", exist_ok=True)
os.makedirs("uploads/verifications", exist_ok=True)


# ── Global ObjectId / datetime sanitiser ──────────────────────────────────────
# Walks every JSON response and converts ObjectId → str, datetime → ISO string.
# This is an app-level safety net so no route can ever leak a raw ObjectId to
# Pydantic's serializer regardless of what the route function returns.

def _sanitise(obj):
    if isinstance(obj, dict):
        return {k: _sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise(v) for v in obj]
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


app = FastAPI(
    title="LokAI – Local Leadership Decision Intelligence Platform",
    description="Civic governance platform for reporting and resolving local issues",
    version="1.0.0",
    lifespan=lifespan
)


@app.middleware("http")
async def sanitise_objectids(request: Request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if "application/json" not in ct:
        return response
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    try:
        data  = json.loads(body)
        clean = _sanitise(data)
        # Rebuild headers without content-length (length may change after sanitise)
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() != "content-length"}
        return JSONResponse(content=clean, status_code=response.status_code,
                            headers=headers)
    except Exception:
        return Response(content=body, status_code=response.status_code,
                        media_type=response.media_type)


# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for uploads (directory is guaranteed to exist now)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Routes
app.include_router(auth.router, prefix="/api/v1")
app.include_router(issues.router, prefix="/api/v1")
app.include_router(verifications.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(analyze_complaint.router, prefix="/api/v1")
app.include_router(social_media_analysis.router, prefix="/api/v1")
app.include_router(feed.router, prefix="/api/v1")
# app.include_router(public_update.router, prefix="/api/v1")
app.include_router(chatbot.router, prefix='/api/v1/chatbot', tags=['chatbot'])


@app.get("/")
async def root():
    return {
        "name": "LokAI API",
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
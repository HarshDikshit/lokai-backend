from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from bson import ObjectId
import bcrypt

from app.schemas.Schemas import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from app.middleware.auth import create_access_token, get_current_user
from app.database.connection import get_database

router = APIRouter(prefix="/auth", tags=["Authentication"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(data: RegisterRequest):
    db = get_database()

    existing = await db.users.find_one({"email": data.email})
    if existing:
        raise HTTPException(400, "Email already registered")

    user_doc = {
        "name": data.name,
        "email": data.email,
        "password_hash": hash_password(data.password),
        "role": data.role.value,
        "failed_cases": 0,
        "created_at": datetime.utcnow()
    }
    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)

    token = create_access_token({"sub": user_id, "role": data.role.value})
    return TokenResponse(
        access_token=token,
        role=data.role.value,
        user_id=user_id,
        name=data.name
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest):
    db = get_database()

    user = await db.users.find_one({"email": data.email})
    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    user_id = str(user["_id"])
    token = create_access_token({"sub": user_id, "role": user["role"]})
    return TokenResponse(
        access_token=token,
        role=user["role"],
        user_id=user_id,
        name=user["name"]
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user["_id"]),
        name=current_user["name"],
        email=current_user["email"],
        role=current_user["role"],
        failed_cases=current_user.get("failed_cases", 0),
        created_at=current_user["created_at"]
    )
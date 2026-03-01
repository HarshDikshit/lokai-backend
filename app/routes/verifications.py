from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from typing import Optional
from datetime import datetime
from bson import ObjectId

from app.middleware.auth import get_current_user, require_leader
from app.database.connection import get_database
from app.services.file_service import save_image

router = APIRouter(prefix="/verifications", tags=["Verifications"])


@router.post("", status_code=201)
async def upload_verification(
    task_id: str = Form(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    before_image: Optional[UploadFile] = File(default=None),
    after_image: Optional[UploadFile] = File(default=None),
    current_user: dict = Depends(require_leader)
):
    db = get_database()
    
    try:
        task = await db.tasks.find_one({"_id": ObjectId(task_id)})
    except Exception:
        raise HTTPException(400, "Invalid task ID")
    if not task:
        raise HTTPException(404, "Task not found")
    
    before_url = None
    after_url = None
    
    if before_image and before_image.filename:
        before_url = await save_image(before_image, "verifications")
    if after_image and after_image.filename:
        after_url = await save_image(after_image, "verifications")
    
    doc = {
        "task_id": ObjectId(task_id),
        "before_image_url": before_url,
        "after_image_url": after_url,
        "latitude": latitude,
        "longitude": longitude,
        "uploaded_by": current_user["_id"],
        "timestamp": datetime.utcnow()
    }
    result = await db.verifications.insert_one(doc)
    return {"message": "Verification uploaded", "verification_id": str(result.inserted_id)}


@router.get("/{task_id}")
async def get_verification(task_id: str, current_user: dict = Depends(get_current_user)):
    db = get_database()
    try:
        ver = await db.verifications.find_one({"task_id": ObjectId(task_id)})
    except Exception:
        raise HTTPException(400, "Invalid task ID")
    if not ver:
        raise HTTPException(404, "Verification not found")
    
    ver["id"] = str(ver.pop("_id"))
    ver["task_id"] = str(ver["task_id"])
    ver["uploaded_by"] = str(ver.get("uploaded_by", ""))
    return ver
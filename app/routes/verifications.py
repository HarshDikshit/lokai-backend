"""
app/routes/verifications.py
"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from typing import Optional
from datetime import datetime
from bson import ObjectId

from app.middleware.auth import get_current_user, require_leader
from app.database.connection import get_database
from utils.cloudinary_utils import upload_image_file

router = APIRouter(prefix="/verifications", tags=["Verifications"])


# ─── POST /verifications ──────────────────────────────────────────────────────
# Called by leader during resolution to upload before/after photos.
# task_id == issue _id  (no separate task collection).
# Images are uploaded to Cloudinary; URLs stored in verifications collection.
@router.post("", status_code=201)
async def upload_verification(
    issue_id:      str                  = Form(...),
    latitude:     Optional[float]      = Form(None),
    longitude:    Optional[float]      = Form(None),
    before_image: Optional[UploadFile] = File(default=None),
    after_image:  Optional[UploadFile] = File(default=None),
    current_user: dict                 = Depends(require_leader),
):
    db = get_database()

    # Validate issue exists
    try:
        issue_oid = ObjectId(issue_id)
        issue = await db.issues.find_one({"_id": issue_oid})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid issue ID")
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Upload to Cloudinary (returns {"url": ..., "public_id": ...} or None)
    before_result: Optional[dict] = None
    if before_image and before_image.filename:
        before_result = await upload_image_file(
            before_image, folder="lokai/verifications/before"
        )

    after_result: Optional[dict] = None
    if after_image and after_image.filename:
        after_result = await upload_image_file(
            after_image, folder="lokai/verifications/after"
        )

    doc = {
        "task_id":                issue_oid,
        "before_image_url":       before_result["url"]       if before_result else None,
        "before_image_public_id": before_result["public_id"] if before_result else None,
        "after_image_url":        after_result["url"]        if after_result  else None,
        "after_image_public_id":  after_result["public_id"]  if after_result  else None,
        "latitude":               latitude,
        "longitude":              longitude,
        "uploaded_by":            current_user["_id"],
        "timestamp":              datetime.utcnow(),
    }
    result = await db.verifications.insert_one(doc)

    return {
        "message":          "Verification uploaded",
        "verification_id":  str(result.inserted_id),
        "before_image_url": doc["before_image_url"],
        "after_image_url":  doc["after_image_url"],
    }


# ─── GET /verifications/{task_id} ─────────────────────────────────────────────
@router.get("/{task_id}")
async def get_verification(
    task_id:      str,
    current_user: dict = Depends(get_current_user),
):
    db = get_database()
    try:
        ver = await db.verifications.find_one({"task_id": ObjectId(task_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid issue ID")
    if not ver:
        raise HTTPException(status_code=404, detail="Verification not found")

    ver["id"]          = str(ver.pop("_id"))
    ver["task_id"]     = str(ver["task_id"])
    ver["uploaded_by"] = str(ver.get("uploaded_by", ""))
    return ver
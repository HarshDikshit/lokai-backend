import os
import uuid
import aiofiles
from fastapi import HTTPException, UploadFile
from pathlib import Path

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/mp4", "audio/webm"}


def get_upload_path(subfolder: str = "") -> Path:
    path = Path(UPLOAD_DIR) / subfolder
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_image(file: UploadFile, subfolder: str = "images") -> str:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, f"Invalid image type: {file.content_type}")
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "File too large (max 10MB)")
    
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4()}.{ext}"
    path = get_upload_path(subfolder) / filename
    
    async with aiofiles.open(path, "wb") as f:
        await f.write(content)
    
    return f"/uploads/{subfolder}/{filename}"


async def save_audio(file: UploadFile, subfolder: str = "audio") -> str:
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(400, f"Invalid audio type: {file.content_type}")
    
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "File too large (max 10MB)")
    
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "mp3"
    filename = f"{uuid.uuid4()}.{ext}"
    path = get_upload_path(subfolder) / filename
    
    async with aiofiles.open(path, "wb") as f:
        await f.write(content)
    
    return f"/uploads/{subfolder}/{filename}"
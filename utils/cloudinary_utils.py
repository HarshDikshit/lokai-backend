"""
app/utils/cloudinary_utils.py
All Cloudinary upload / delete helpers used across the app.
"""

import os
import uuid
import aiofiles
import cloudinary
import cloudinary.uploader
from typing import Optional
from fastapi import HTTPException, UploadFile

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/mp4", "audio/webm", "audio/x-wav"}
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_SIZE", 10 * 1024 * 1024))  # 10 MB default


# ─── Internal ─────────────────────────────────────────────────────────────────

async def _save_to_tmp(upload_file: UploadFile) -> str:
    ext = ""
    if upload_file.filename and "." in upload_file.filename:
        ext = "." + upload_file.filename.rsplit(".", 1)[-1].lower()
    tmp_path = f"/tmp/lokai_{uuid.uuid4().hex}{ext}"
    content = await upload_file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(400, "File exceeds 10 MB limit")
    async with aiofiles.open(tmp_path, "wb") as f:
        await f.write(content)
    return tmp_path


def _cleanup(path: str) -> None:
    try:
        os.remove(path)
    except Exception:
        pass


# ─── Core upload (path → Cloudinary) ─────────────────────────────────────────

async def upload_image(tmp_path: str, folder: str = "lokai/issues") -> dict:
    """Returns {"url": str, "public_id": str}"""
    try:
        r = cloudinary.uploader.upload(
            tmp_path,
            folder=folder,
            resource_type="image",
            transformation=[{"quality": "auto", "fetch_format": "auto"}],
        )
        return {"url": r["secure_url"], "public_id": r["public_id"]}
    except Exception as e:
        raise HTTPException(500, f"Image upload failed: {e}")


async def upload_audio(tmp_path: str, folder: str = "lokai/audio") -> dict:
    """Returns {"url": str, "public_id": str}. Cloudinary uses resource_type=video for audio."""
    try:
        r = cloudinary.uploader.upload(tmp_path, folder=folder, resource_type="video")
        return {"url": r["secure_url"], "public_id": r["public_id"]}
    except Exception as e:
        raise HTTPException(500, f"Audio upload failed: {e}")


# ─── Public wrappers (UploadFile → validate → tmp → Cloudinary) ──────────────

async def upload_image_file(file: Optional[UploadFile], folder: str = "lokai/issues") -> Optional[dict]:
    """Validate, upload to Cloudinary. Returns {"url", "public_id"} or None."""
    if not file or not file.filename:
        return None
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, f"Unsupported image type: {file.content_type}")
    tmp = await _save_to_tmp(file)
    try:
        return await upload_image(tmp, folder=folder)
    finally:
        _cleanup(tmp)


async def upload_audio_file(file: Optional[UploadFile], folder: str = "lokai/audio") -> Optional[dict]:
    """Validate, upload to Cloudinary. Returns {"url", "public_id"} or None."""
    if not file or not file.filename:
        return None
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(400, f"Unsupported audio type: {file.content_type}")
    tmp = await _save_to_tmp(file)
    try:
        return await upload_audio(tmp, folder=folder)
    finally:
        _cleanup(tmp)


# ─── Delete ───────────────────────────────────────────────────────────────────

async def delete_image(public_id: str) -> bool:
    try:
        r = cloudinary.uploader.destroy(public_id, resource_type="image")
        return r.get("result") == "ok"
    except Exception as e:
        print(f"[Cloudinary] delete_image failed {public_id}: {e}")
        return False


async def delete_audio(public_id: str) -> bool:
    try:
        r = cloudinary.uploader.destroy(public_id, resource_type="video")
        return r.get("result") == "ok"
    except Exception as e:
        print(f"[Cloudinary] delete_audio failed {public_id}: {e}")
        return False


async def delete_issue_files(image_public_ids: list, audio_public_id: Optional[str]) -> None:
    """Convenience bulk-delete for when an issue is deleted."""
    for pid in (image_public_ids or []):
        await delete_image(pid)
    if audio_public_id:
        await delete_audio(audio_public_id)
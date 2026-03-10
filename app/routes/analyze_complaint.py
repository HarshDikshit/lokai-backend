from fastapi import APIRouter, FastAPI, UploadFile, File, Form
from models_analyze_complaint.ai_pipeline  import run_pipeline
import shutil, os

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
    
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/analyze_complaint/")
async def analyze_complaint(
    text: str = Form(None),
    image: UploadFile = File(None),
    audio: UploadFile = File(None)
):

    image_path = None
    audio_path = None

    if image:
        image_path = f"{UPLOAD_DIR}/{image.filename}"
        with open(image_path,"wb") as buffer:
            shutil.copyfileobj(image.file,buffer)

    if audio:
        audio_path = f"{UPLOAD_DIR}/{audio.filename}"
        with open(audio_path,"wb") as buffer:
            shutil.copyfileobj(audio.file,buffer)
        print("Audio saved at:", audio_path)    

    result = run_pipeline(text, audio_path, image_path)

    return result
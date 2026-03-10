from transformers import pipeline
from pydub import AudioSegment
import os

speech_to_text = pipeline(
    "automatic-speech-recognition",
    model="openai/whisper-base",
    device=-1
)

def transcribe_audio(audio_path):

    try:
        # Convert to WAV
        audio = AudioSegment.from_file(audio_path)

        wav_path = audio_path + ".wav"

        audio.export(wav_path, format="wav")

        # Run Whisper
        result = speech_to_text(wav_path)

        return result["text"]

    except Exception as e:
        print("Audio processing error:", e)
        return ""
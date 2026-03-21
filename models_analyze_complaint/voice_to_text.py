import librosa
import numpy as np
from pydub import AudioSegment
from transformers import pipeline

# Use device=0 for Colab's GPU if available, else -1
speech_to_text = pipeline(
    "automatic-speech-recognition",
    model="openai/whisper-base",
    device=0 # Change to -1 if not using GPU
)

def transcribe_audio(audio_path):
    try:
        # 1. Use Pydub to decode the audio (it handles WhatsApp .mp4/.m4a best)
        audio = AudioSegment.from_file(audio_path)
        
        # 2. Set to 16000Hz (Whisper requirement) and Mono
        audio = audio.set_frame_rate(16000).set_channels(1)
        
        # 3. Convert to a format the AI understands (Numpy array)
        channel_sounds = audio.get_array_of_samples()
        audio_array = np.array(channel_sounds).astype(np.float32) / 32768.0 # Normalize

        # 4. Run Whisper
        result = speech_to_text(audio_array)
        return result["text"]

    except Exception as e:
        print(f"Transcription Error: {e}")
        # Final fallback: Try path-based if array-based fails
        try:
             res = speech_to_text(audio_path)
             return res["text"]
        except:
             return ""
"""Local speech-to-text: records a few seconds from the laptop's default microphone and
transcribes it with a local Whisper ("small") model - no cloud call, no API key. Used by the
UI's manual "Listen" button (see server.py /api/listen); nothing calls this automatically yet,
since there's no wake-word/VAD trigger wired in - that's the next step once the robot's own
camera/audio APIs are available.
"""
import numpy as np
import sounddevice as sd
import whisper

SAMPLE_RATE = 16000  # what Whisper expects; recording at this rate avoids a resample step
RECORD_SECONDS = 4.0

_model = None


def get_model():
    """Loads the small model once and reuses it - loading takes a few seconds, transcribing
    a short clip does not, so we don't want to pay the load cost on every button press."""
    global _model
    if _model is None:
        _model = whisper.load_model("small")
    return _model


def record_audio(seconds: float = RECORD_SECONDS) -> np.ndarray:
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return audio.reshape(-1)


def record_and_transcribe(seconds: float = RECORD_SECONDS) -> str:
    audio = record_audio(seconds)
    result = get_model().transcribe(audio, fp16=False, language="en")
    return result["text"].strip()

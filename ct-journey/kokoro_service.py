"""Standalone local TTS microservice using Kokoro-82M (free, open-weight, CPU-friendly).

Runs under its own Python 3.12 venv (kokoro_venv/) because the `kokoro` package requires
Python <3.13 - incompatible with the 3.14 interpreter the rest of this project uses. Started
as a subprocess by run.py, exactly like patient_id.service; talked to over plain HTTP so the
main app's Python version never has to match this one.
"""
import argparse
import io

import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from kokoro import KPipeline

VOICE = "af_heart"  # Kokoro's warmest/most natural American-English female voice
SAMPLE_RATE = 24000

app = FastAPI(title="Kokoro TTS")
_pipeline = None


def get_pipeline() -> KPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = KPipeline(lang_code="a")  # "a" = American English
    return _pipeline


def warm_up() -> None:
    """Loads the pipeline AND runs one throwaway synthesis before this process ever starts
    serving. Without this, the lazy-load happened on the first real /synthesize call - which
    meant the robot's very first spoken line, mid-interaction, silently ate the ~8-10s cold
    load. run.py's startup already waits for /health, so paying that cost here (while the
    rest of the stack is also still starting up) is free; paying it live never should be."""
    list(get_pipeline()("Hello.", voice=VOICE))


@app.get("/health")
def health():
    return {"status": "ok", "voice": VOICE}


@app.get("/synthesize")
def synthesize(text: str):
    if not text.strip():
        raise HTTPException(400, "text is required")
    chunks = []
    for _, _, audio in get_pipeline()(text, voice=VOICE):
        chunks.append(audio)
    if not chunks:
        raise HTTPException(502, "kokoro produced no audio")
    import numpy as np
    full_audio = np.concatenate(chunks)
    buf = io.BytesIO()
    sf.write(buf, full_audio, SAMPLE_RATE, format="WAV")
    return Response(buf.getvalue(), media_type="audio/wav")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8071)
    args = ap.parse_args()
    warm_up()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")

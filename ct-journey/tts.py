"""Olaf's real voice. Three tiers, in order:
  1. ElevenLabs cloud TTS - best quality, needs internet + a working ELEVENLABS_API_KEY
     (see .env, never hardcoded/committed). Currently failing on this account (402: the
     configured voice needs a paid plan to use via the API) - every call falls through to #2.
  2. Kokoro-82M (kokoro_service.py) - free, open-weight, fully local/offline. Runs under its
     own Python 3.12 venv (kokoro_venv/) since the `kokoro` package needs Python <3.13 and
     this project otherwise runs on 3.14; reached over plain HTTP, started by run.py.
  3. The viewing browser's own built-in voice (app.js) - only if BOTH of the above fail
     outright (e.g. this whole process can't reach either service), so Olaf is never
     silently mute.
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

import journey_config

# Must run before `from elevenlabs import ...` - the SDK reads ELEVENLABS_API_KEY from the
# environment at import time, not at ElevenLabs() construction time, so loading .env any
# later silently leaves the client unauthenticated even though os.environ looks correct.
load_dotenv(Path(__file__).resolve().parent / ".env")

from elevenlabs import ElevenLabs  # noqa: E402

VOICE_ID = "kfGEdprt9Oe4pbdP8VTo"  # https://elevenlabs.io/voices/kfGEdprt9Oe4pbdP8VTo
MODEL_ID = "eleven_flash_v2_5"  # lowest latency - this is an interactive kiosk, not a narration

_client = None
_cache: dict[str, tuple[bytes, str]] = {}  # text -> (audio_bytes, media_type)
_CACHE_LIMIT = 200  # this demo repeats a small, fixed set of lines - cache them all easily


def get_client() -> ElevenLabs:
    global _client
    if _client is None:
        # Passed explicitly (not relying on the SDK's own env lookup) so load order can
        # never bite again - we control exactly when this value is read.
        _client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    return _client


def _synthesize_elevenlabs(text: str) -> bytes:
    chunks = get_client().text_to_speech.convert(text=text, voice_id=VOICE_ID, model_id=MODEL_ID)
    return b"".join(chunks)


def _synthesize_kokoro(text: str) -> bytes:
    r = requests.get(f"{journey_config.KOKORO_SERVICE_URL}/synthesize", params={"text": text}, timeout=20)
    r.raise_for_status()
    return r.content


def synthesize_audio(text: str) -> tuple[bytes, str]:
    """Returns (audio_bytes, media_type). Tries ElevenLabs, then Kokoro; only raises if both
    fail, so the caller's own browser-voice fallback is the true last resort."""
    cached = _cache.get(text)
    if cached is not None:
        return cached

    try:
        result = (_synthesize_elevenlabs(text), "audio/mpeg")
    except Exception as eleven_exc:
        try:
            result = (_synthesize_kokoro(text), "audio/wav")
        except Exception as kokoro_exc:
            raise RuntimeError(
                f"elevenlabs failed ({eleven_exc}); kokoro also failed ({kokoro_exc})"
            ) from kokoro_exc

    if len(_cache) >= _CACHE_LIMIT:
        _cache.pop(next(iter(_cache)))
    _cache[text] = result
    return result

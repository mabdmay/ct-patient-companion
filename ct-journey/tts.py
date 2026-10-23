"""Olaf's real voice: ElevenLabs cloud text-to-speech (replaces the earlier local Piper
model per explicit request - ElevenLabs only, no local TTS fallback at this layer). Needs
internet access and ELEVENLABS_API_KEY (see .env, never hardcoded/committed - see
onboarding via `npx -y @elevenlabs/cli@latest onboard init`). app.js still falls back to the
browser's own built-in voice if the /api/tts request itself fails (network hiccup etc.), so
Olaf is never silently mute - but when this succeeds, this is the voice that's heard.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Must run before `from elevenlabs import ...` - the SDK reads ELEVENLABS_API_KEY from the
# environment at import time, not at ElevenLabs() construction time, so loading .env any
# later silently leaves the client unauthenticated even though os.environ looks correct.
load_dotenv(Path(__file__).resolve().parent / ".env")

from elevenlabs import ElevenLabs  # noqa: E402

#   Originally requested: https://elevenlabs.io/voices/0ggs85h7hrWz8ExXnsBc - that's a public
#   "voice library" voice, which ElevenLabs blocks via the API on this account's plan (402
#   "Free users cannot use library voices via the API"). Using Sarah instead: a default
#   premade voice (female, soft) bundled with every account, confirmed working on this key.
VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # Sarah
MODEL_ID = "eleven_flash_v2_5"  # lowest latency - this is an interactive kiosk, not a narration

_client = None
_cache: dict[str, bytes] = {}
_CACHE_LIMIT = 200  # this demo repeats a small, fixed set of lines - cache them all easily


def get_client() -> ElevenLabs:
    global _client
    if _client is None:
        # Passed explicitly (not relying on the SDK's own env lookup) so load order can
        # never bite again - we control exactly when this value is read.
        _client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    return _client


def synthesize_mp3(text: str) -> bytes:
    cached = _cache.get(text)
    if cached is not None:
        return cached
    chunks = get_client().text_to_speech.convert(text=text, voice_id=VOICE_ID, model_id=MODEL_ID)
    audio_bytes = b"".join(chunks)
    if len(_cache) >= _CACHE_LIMIT:
        _cache.pop(next(iter(_cache)))
    _cache[text] = audio_bytes
    return audio_bytes

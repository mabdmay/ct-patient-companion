"""Local-only web UI for the patient journey, served to a browser on the robot's screen."""
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

# This UI gets actively edited while the demo is running (new stages, new elements) - a
# stale cached index.html paired with a freshly-fetched app.js (or vice versa) can crash the
# page outright (a DOM lookup the older file doesn't know about). Never let the WebView cache
# these three, so every load always gets a matching set.
NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate"}

import journey_config
import tts
from state import JourneyState

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"


class CameraSourceChoice(BaseModel):
    source: str  # "external", "robot" or "none"
    robot_id: str | None = None


def create_app(state: JourneyState, runner=None) -> FastAPI:
    app = FastAPI(title="CT Patient Journey UI")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE_HEADERS)

    @app.get("/diag")
    def diag():
        """Staged diagnostic page (plain HTML -> inline JS -> external CSS -> fetch -> CSS
        animation) to find exactly where rendering breaks on a device we have no logs for."""
        return FileResponse(WEB_DIR / "diag.html", headers=NO_CACHE_HEADERS)

    @app.post("/api/next")
    def next_stage(choice: int = 0):
        """Advance the journey. `choice` is the index of the pressed button in the current
        stage's `choices` (0 when the stage only offers one way on) - that is what picks the
        branch, so this is the only thing that moves the journey forward."""
        if runner is not None:
            runner.advance(choice)
        return {"ok": True}

    @app.post("/api/camera-source")
    def camera_source_choice(body: CameraSourceChoice):
        """The UI's pre-connect camera screen calls this exactly once per run, before the
        journey (and any camera) starts - see runner.py JourneyRunner.choose_camera_source."""
        if body.source not in ("external", "robot", "none"):
            raise HTTPException(400, "source must be 'external', 'robot' or 'none'")
        if runner is not None:
            runner.choose_camera_source(body.source, body.robot_id)
        return {"ok": True}

    @app.get("/app.js")
    def app_js():
        return FileResponse(WEB_DIR / "app.js", media_type="application/javascript", headers=NO_CACHE_HEADERS)

    @app.get("/style.css")
    def style_css():
        return FileResponse(WEB_DIR / "style.css", media_type="text/css", headers=NO_CACHE_HEADERS)

    @app.get("/api/state")
    def get_state():
        return state.snapshot()

    @app.get("/api/tts")
    def tts_audio(text: str):
        """Synthesizes `text` - Olaf's real voice, instead of whatever TTS engine (often
        robotic) the viewing browser happens to have installed. Tries ElevenLabs, falls back
        to the local Kokoro service, and only 502s (letting app.js fall back to the browser's
        own voice) if both fail. Repeated lines are cached (see tts.py)."""
        if not text.strip():
            raise HTTPException(400, "text is required")
        try:
            audio_bytes, media_type = tts.synthesize_audio(text)
        except Exception as exc:
            raise HTTPException(502, f"tts failed: {exc}")
        return Response(audio_bytes, media_type=media_type)

    @app.get("/api/camera/live.jpg")
    def live_camera():
        jpeg = state.get_camera_frame()
        if jpeg is None:
            raise HTTPException(503, "camera not ready yet")
        return Response(jpeg, media_type="image/jpeg")

    @app.get("/api/camera/stream.mjpg")
    async def camera_stream():
        """MJPEG stream (multipart/x-mixed-replace): an <img> can play this directly, no JS
        polling needed - pushes a new frame as soon as one lands instead of on a fixed timer."""
        async def generate():
            last = None
            try:
                while True:
                    jpeg = state.get_camera_frame()
                    if jpeg is not None and jpeg is not last:
                        last = jpeg
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                return
        return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/examples/{name}")
    def example_image(name: str):
        example_dir = journey_config.POSE_EXAMPLE_DIR.resolve()
        path = (example_dir / name).resolve()
        if path.parent != example_dir or not path.is_file():
            raise HTTPException(404, "unknown example image")
        return FileResponse(path)

    return app

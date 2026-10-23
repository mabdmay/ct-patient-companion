"""Local-only web UI for the patient journey, served to a browser on the robot's screen."""
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

import journey_config
from state import JourneyState

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"


def create_app(state: JourneyState, runner=None) -> FastAPI:
    app = FastAPI(title="CT Patient Journey UI")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.post("/api/next")
    def next_stage():
        if runner is not None:
            runner.advance()
        return {"ok": True}

    @app.get("/app.js")
    def app_js():
        return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")

    @app.get("/style.css")
    def style_css():
        return FileResponse(WEB_DIR / "style.css", media_type="text/css")

    @app.get("/api/state")
    def get_state():
        return state.snapshot()

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

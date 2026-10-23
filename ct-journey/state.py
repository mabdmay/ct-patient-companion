"""Shared, thread-safe journey state: written by runner.py, read by the FastAPI endpoints."""
import threading
import time


class JourneyState:
    def __init__(self):
        self._lock = threading.Lock()
        self.stage_index = 0
        self.stage_id = None
        self.title = ""
        self.message = ""
        self.stage_started_at = time.monotonic()
        self.stage_duration = 0.0
        self.detected_name = None
        self.detected_score = None
        self.confirm_text = None
        self.track_status = None
        self.posture_status = None
        self.posture_reasons: list[str] = []
        self.example_images: list[str] = []
        self.speak_seq = 0
        self.camera_frame_jpeg: bytes | None = None
        self.manual = False
        self.watching = False  # True while the robot is actively using the camera this stage

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "stage_index": self.stage_index,
                "stage_id": self.stage_id,
                "title": self.title,
                "message": self.message,
                "elapsed": round(time.monotonic() - self.stage_started_at, 1),
                "duration": self.stage_duration,
                "detected_name": self.detected_name,
                "detected_score": self.detected_score,
                "track_status": self.track_status,
                "posture_status": self.posture_status,
                "posture_reasons": self.posture_reasons,
                "example_images": self.example_images,
                "speak_seq": self.speak_seq,
                "manual": self.manual,
                "watching": self.watching,
            }

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def set_message(self, message: str) -> None:
        """Update the spoken/displayed message; bumps speak_seq only when the text changes,
        so the browser doesn't re-speak an unchanged instruction on every poll."""
        with self._lock:
            if message and message != self.message:
                self.message = message
                self.speak_seq += 1

    def enter_stage(self, index: int, stage_id: str, title: str, message: str, duration: float) -> None:
        with self._lock:
            self.stage_index = index
            self.stage_id = stage_id
            self.title = title
            self.stage_started_at = time.monotonic()
            self.stage_duration = duration
            if message != self.message:
                self.message = message
                self.speak_seq += 1

    def set_camera_frame(self, jpeg_bytes: bytes) -> None:
        with self._lock:
            self.camera_frame_jpeg = jpeg_bytes

    def get_camera_frame(self) -> bytes | None:
        with self._lock:
            return self.camera_frame_jpeg

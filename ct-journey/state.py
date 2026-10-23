"""Shared, thread-safe journey state: written by runner.py, read by the FastAPI endpoints."""
import threading


class JourneyState:
    def __init__(self):
        self._lock = threading.Lock()
        self.stage_id = None
        self.phase = 0
        self.title = ""
        self.message = ""
        self.choices: list[str] = []  # button labels for this stage, in order
        self.detected_name = None
        self.detected_patient_id = None
        self.detected_score = None
        self.track_status = None
        self.posture_status = None
        self.posture_reasons: list[str] = []
        self.example_images: list[str] = []
        self.speak_seq = 0
        self.camera_frame_jpeg: bytes | None = None
        self.watching = False  # True while the robot is actively using the camera this stage
        self.face_aligned = None  # None = n/a this stage, False = known face seen but not centered yet, True = aligned
        self.camera_source = None  # "external", "robot" or "none", set once the runner starts
        self.robot_id = None  # the robot's deviceId, when camera_source == "robot"

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "stage_id": self.stage_id,
                "phase": self.phase,
                "title": self.title,
                "message": self.message,
                "choices": list(self.choices),
                "detected_name": self.detected_name,
                "detected_score": self.detected_score,
                "track_status": self.track_status,
                "posture_status": self.posture_status,
                "posture_reasons": self.posture_reasons,
                "example_images": self.example_images,
                "speak_seq": self.speak_seq,
                "watching": self.watching,
                "face_aligned": self.face_aligned,
                "camera_source": self.camera_source,
                "robot_id": self.robot_id,
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

    def enter_stage(self, stage, message: str, choices: list[str]) -> None:
        """Entering a stage always bumps speak_seq when there's something to say - even if
        the line is identical to the previous stage's. The script calls the patient's name
        twice in a row, and the second call-out has to actually be spoken again."""
        with self._lock:
            self.stage_id = stage.id
            self.phase = stage.phase
            self.title = stage.title
            self.message = message
            self.choices = list(choices)
            if message:
                self.speak_seq += 1

    def reset_patient(self) -> None:
        """Back to the top of the loop for the next appointment - forget who the last
        patient was so the waiting-room call-out starts from the schedule again."""
        with self._lock:
            self.detected_name = None
            self.detected_patient_id = None
            self.detected_score = None
            self.track_status = None
            self.posture_status = None
            self.posture_reasons = []
            self.face_aligned = None

    def set_camera_frame(self, jpeg_bytes: bytes) -> None:
        with self._lock:
            self.camera_frame_jpeg = jpeg_bytes

    def get_camera_frame(self) -> bytes | None:
        with self._lock:
            return self.camera_frame_jpeg

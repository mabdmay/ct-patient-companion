"""Background thread that drives the journey timeline. Owns the one physical camera and, per
active stage, either posts frames to the face-id service over HTTP (identify/track) or runs
the positioning library's pose checks on them directly (pose_monitoring).

A dedicated CameraReader thread continuously drains the camera (its own native frame rate,
not throttled) so the live preview is smooth regardless of how often the heavier sensing
calls (HTTP identify/track, YOLO pose) actually run.

In manual mode, stages still run real sensing while waiting - they just advance on a UI
click (`advance()`) instead of a fixed timer.
"""
import itertools
import sys
import threading
import time

import cv2
import requests

import face_client
import journey_config
import stages as stages_mod
from guidance_text import guidance_for
from pose_bridge import PoseBridge
from state import JourneyState

sys.path.insert(0, str(journey_config.FACE_ID_REPO))
from patient_id.gateway import GatewayClient  # noqa: E402

POLL_INTERVAL = 0.5
JPEG_QUALITY = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
CAMERA_KINDS = ("call_and_wait", "identify", "track", "pose_loop")
CAMERA_OFF_NOTE = " (Camera unavailable.)"


class CameraReader(threading.Thread):
    """Keeps draining the camera as fast as it'll deliver frames. While `show_raw` is True,
    also keeps the UI's live preview updated; pose_monitoring turns that off so its own
    annotated overlay (written at the slower inference cadence) isn't instantly overwritten.
    """

    def __init__(self, camera: cv2.VideoCapture, state: JourneyState):
        super().__init__(daemon=True)
        self.camera = camera
        self.state = state
        self.show_raw = True
        self._lock = threading.Lock()
        self._frame = None
        self._stop = threading.Event()

    def latest_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            ok, frame = self.camera.read()
            if not ok:
                time.sleep(0.03)
                continue
            with self._lock:
                self._frame = frame
            if self.show_raw:
                ok, buf = cv2.imencode(".jpg", frame, JPEG_QUALITY)
                if ok:
                    self.state.set_camera_frame(buf.tobytes())


class JourneyRunner(threading.Thread):
    def __init__(self, state: JourneyState, manual: bool = False, camera_index: int | None = None):
        super().__init__(daemon=True)
        self.state = state
        self.manual = manual
        self.camera_index = camera_index if camera_index is not None else journey_config.CAMERA_INDEX
        self.pose_bridge = PoseBridge()
        self.camera = None
        self.reader: CameraReader | None = None
        self.gateway = GatewayClient(journey_config.GATEWAY_URL, journey_config.ROBOT_DEVICE_ID)
        self._workflow_seq = itertools.count(1)
        self._last_pushed_text = None
        self._last_pushed_at = 0.0
        self._stop = threading.Event()
        self._next_event = threading.Event()

    def stop(self) -> None:
        self._stop.set()
        self._next_event.set()
        if self.reader is not None:
            self.reader.stop()
        if self.camera is not None:
            self.camera.release()

    def advance(self) -> None:
        """Called from the UI's 'Next' button."""
        self._next_event.set()

    def run(self) -> None:
        self.state.update(manual=self.manual)
        self.camera = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not self.camera.isOpened():
            print(f"[journey] warning: camera {self.camera_index} did not open")
        else:
            self.reader = CameraReader(self.camera, self.state)
            self.reader.start()
        while not self._stop.is_set():
            for index, stage in enumerate(stages_mod.STAGES):
                self._run_stage(index, stage)
                if self._stop.is_set():
                    return
            if not self.manual:
                time.sleep(2)  # loop the whole journey for a continuous demo

    def _camera_available(self) -> bool:
        return self.reader is not None

    def _push_to_robot(self, title: str, text: str) -> None:
        """Mirror the current instruction onto the real robot's screen (no-op/dry-run until
        journey_config.GATEWAY_URL and ROBOT_DEVICE_ID are set). Throttled and deduped so a
        fast-changing local message (e.g. posture corrections) doesn't flood the shared
        gateway with a new workflow every tick."""
        if text == self._last_pushed_text:
            return
        now = time.monotonic()
        if now - self._last_pushed_at < journey_config.GATEWAY_MIN_INTERVAL_S:
            return
        self._last_pushed_text = text
        self._last_pushed_at = now
        workflow_id = f"ct-journey-{next(self._workflow_seq)}"
        try:
            self.gateway.publish_screen(workflow_id, title, text)
        except RuntimeError as exc:  # a gateway hiccup must never break the journey
            print(f"[journey] gateway push failed: {exc}")

    def _capture_jpeg(self) -> bytes | None:
        if self.reader is None:
            return None
        frame = self.reader.latest_frame()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, JPEG_QUALITY)
        return buf.tobytes() if ok else None

    def _run_stage(self, index, stage) -> None:
        message = stages_mod.render_message(stage, self.state, journey_config)
        camera_ready = self._camera_available()
        if stage.kind in CAMERA_KINDS and not camera_ready:
            message += CAMERA_OFF_NOTE
        duration = 0.0 if self.manual else stage.duration
        self.state.enter_stage(index, stage.id, stage.title, message, duration)
        self._push_to_robot(stage.title, message)

        self.state.update(example_images=journey_config.POSE_EXAMPLE_IMAGE_NAMES if stage.kind == "examples" else [])
        if stage.kind != "pose_loop":
            self.state.update(posture_status=None, posture_reasons=[])
        if stage.kind != "track":
            self.state.update(track_status=None)
        self.state.update(watching=stage.kind in CAMERA_KINDS)
        if self.reader is not None:
            self.reader.show_raw = stage.kind != "pose_loop"

        identify_confirmed = False
        self._next_event.clear()
        # "call_and_wait" always blocks on actually recognizing the patient - no timeout,
        # manual or not. The 'Next' button is still a manual escape hatch if needed.
        waits_for_detection = stage.kind == "call_and_wait"
        deadline = None if (self.manual or waits_for_detection) else time.monotonic() + stage.duration
        while not self._stop.is_set():
            if self._next_event.is_set():  # always a valid escape, even outside manual mode
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            if stage.kind == "call_and_wait" and camera_ready:
                if self._identify_tick(stage.id):
                    break
            elif stage.kind == "track" and camera_ready:
                self._poll_track()
            elif stage.kind == "pose_loop" and camera_ready:
                self._pose_tick()
            elif stage.kind == "identify" and camera_ready and not identify_confirmed:
                identify_confirmed = self._identify_tick(stage.id)
            time.sleep(POLL_INTERVAL)
        self._next_event.clear()

    def _identify_tick(self, stage_id: str) -> bool:
        """One identify attempt against the live camera. Keeps retrying (called again next
        tick) until a known patient is found, so the user has time to step into frame."""
        jpeg = self._capture_jpeg()
        if jpeg is None:
            return False
        try:
            faces = face_client.identify_bytes(jpeg)
        except requests.RequestException as exc:
            print(f"[journey] identify failed: {exc}")
            return False
        match = face_client.best_match(faces, journey_config.DEMO_PATIENT_ID)
        if not match:
            return False
        self.state.update(detected_name=match["name"], detected_score=match["score"])
        confirm = f"Yes, I can see it's still {match['name']}."
        try:
            face_client.watch([journey_config.DEMO_PATIENT_ID])
        except requests.RequestException:
            pass
        self.state.update(confirm_text=confirm)
        if stage_id in ("confirm_at_changing_room", "confirm_after_changing"):
            self.state.set_message(confirm)
            self._push_to_robot(self.state.title, confirm)
        return True

    def _poll_track(self) -> None:
        jpeg = self._capture_jpeg()
        if jpeg is None:
            return
        try:
            status = face_client.track_frame_bytes(jpeg)
        except requests.RequestException:
            return
        self.state.update(track_status=status)

    def _pose_tick(self) -> None:
        frame = self.reader.latest_frame() if self.reader is not None else None
        if frame is None:
            return
        try:
            assessment, rendered = self.pose_bridge.assess_and_annotate(frame)
        except Exception as exc:  # the pose model/geometry code must never crash the journey
            print(f"[journey] pose assessment failed: {exc}")
            return
        ok, buf = cv2.imencode(".jpg", rendered, JPEG_QUALITY)
        if ok:
            self.state.set_camera_frame(buf.tobytes())
        self.state.update(posture_status=assessment.status.value, posture_reasons=assessment.reasons)
        guidance = guidance_for(assessment.reasons)
        self.state.set_message(guidance)
        self._push_to_robot(self.state.title, guidance)

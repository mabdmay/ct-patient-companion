"""Background thread that drives the journey timeline. Owns the frame source (see
camera_source.py - either the laptop's own USB camera, or the real robot's camera via the
ACU Gateway) and, per active stage, either posts frames to the face-id service over HTTP
(identify/track) or runs the positioning library's pose checks on them directly
(pose_monitoring).

The frame source runs its own background thread draining frames at their native rate (not
throttled) so the live preview is smooth regardless of how often the heavier sensing calls
(HTTP identify/track, YOLO pose) actually run.

In manual mode, stages still run real sensing while waiting - they just advance on a UI
click (`advance()`) instead of a fixed timer.
"""
import itertools
import sys
import threading
import time

import cv2
import requests

import camera_source
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


class JourneyRunner(threading.Thread):
    def __init__(self, state: JourneyState, manual: bool = False, camera_index: int | None = None,
                 camera_source_choice: str = "ask", robot_id: str | None = None):
        super().__init__(daemon=True)
        self.state = state
        self.manual = manual
        self.camera_index = camera_index if camera_index is not None else journey_config.CAMERA_INDEX
        self.camera_source_choice = camera_source_choice
        self.robot_id_override = robot_id
        self.pose_bridge = PoseBridge()
        self.reader = None  # a camera_source.LocalCameraSource or RobotCameraSource
        self.gateway = GatewayClient(journey_config.GATEWAY_URL, journey_config.ROBOT_DEVICE_ID)
        self._workflow_seq = itertools.count(1)
        self._last_pushed_text = None
        self._last_pushed_at = 0.0
        self._stop = threading.Event()
        self._next_event = threading.Event()
        # "ask" (the default) means: don't touch any camera until the UI's pre-connect
        # screen tells us which source to use (see choose_camera_source / server.py
        # POST /api/camera-source) - a concrete CLI choice resolves this immediately instead.
        self._source_chosen = threading.Event()
        if camera_source_choice != "ask":
            self._source_chosen.set()

    def stop(self) -> None:
        self._stop.set()
        self._next_event.set()
        self._source_chosen.set()  # unblock a run() still waiting on a source choice
        if self.reader is not None:
            self.reader.stop()

    def advance(self) -> None:
        """Called from the UI's 'Next' button."""
        self._next_event.set()

    def choose_camera_source(self, choice: str, robot_id: str | None = None) -> None:
        """Called from the UI's pre-connect "External camera / Robot cameras" screen (see
        server.py POST /api/camera-source). Only takes effect the first time - once the
        journey has started on a given source, switching mid-journey isn't supported."""
        if self._source_chosen.is_set():
            return
        self.camera_source_choice = choice
        self.robot_id_override = robot_id
        self._source_chosen.set()

    def run(self) -> None:
        self.state.update(manual=self.manual)
        self._source_chosen.wait()
        if self._stop.is_set():
            return
        self.reader, resolved_source, resolved_robot_id = camera_source.build_camera_source(
            self.camera_source_choice, self.camera_index, state=self.state, robot_id=self.robot_id_override)
        self.state.update(camera_source=resolved_source, robot_id=resolved_robot_id)
        if not self.reader.ok:
            self.reader = None
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
        except (RuntimeError, requests.exceptions.RequestException) as exc:
            # A gateway hiccup (bad HTTP response, or - as happened here - the gateway being
            # completely unreachable: connect timeout/refused) must never kill this thread.
            # It used to: gateway._call() raises plain RuntimeError for HTTP errors but lets
            # requests' own network exceptions (ConnectTimeout etc.) propagate uncaught, which
            # silently killed the whole journey loop while the HTTP API stayed up - advance()
            # kept returning {"ok": true} with nothing left alive to read it.
            print(f"[journey] gateway push failed: {exc}")

    def _capture_jpeg(self) -> bytes | None:
        if self.reader is None:
            return None
        return self.reader.latest_jpeg()

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
        if stage.kind not in ("call_and_wait", "identify"):
            self.state.update(face_aligned=None)
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

    def _face_aligned(self, box: list[float], frame) -> bool:
        """True once a detected face's box is centered and large enough inside the on-screen
        alignment guide - so the patient has a moment to step into position before a match
        actually counts, instead of being confirmed the instant any face flashes past."""
        if frame is None:
            return True  # no frame to check against (shouldn't happen); don't block forever
        fh, fw = frame.shape[:2]
        x, y, w, h = box
        cx, cy = x + w / 2, y + h / 2
        mx, my = fw * journey_config.FACE_FRAME_MARGIN_X, fh * journey_config.FACE_FRAME_MARGIN_Y
        centered = mx <= cx <= fw - mx and my <= cy <= fh - my
        big_enough = w >= fw * journey_config.FACE_FRAME_MIN_WIDTH_FRAC
        return centered and big_enough

    def _identify_tick(self, stage_id: str) -> bool:
        """One identify attempt against the live camera. Keeps retrying (called again next
        tick) until a known patient is found centered in the on-screen alignment guide, so
        the user has time to step into frame and line their face up before anything counts.

        The first identification (waiting room) auto-selects whichever registered patient
        is actually in frame (Abdullah or Taimoor, etc - anyone in patients.json). Every
        later "confirm it's still you" stage then locks onto that same patient_id, so a
        different registered person wandering into frame later is never mistaken for them.
        """
        jpeg = self._capture_jpeg()
        if jpeg is None:
            return False
        try:
            faces = face_client.identify_bytes(jpeg)
        except requests.RequestException as exc:
            print(f"[journey] identify failed: {exc}")
            return False
        expected_id = journey_config.DEMO_PATIENT_ID if stage_id == "waiting_room_call" else self.state.detected_patient_id
        match = face_client.best_match(faces, expected_id)
        if not match:
            self.state.update(face_aligned=False)
            return False
        aligned = self._face_aligned(match["box"], self.reader.latest_bgr() if self.reader else None)
        self.state.update(face_aligned=aligned)
        if not aligned:
            return False  # known face seen, but not yet centered/close enough - keep waiting
        self.state.update(detected_name=match["name"], detected_patient_id=match["patient_id"], detected_score=match["score"])
        confirm = f"Yes, I can see it's still {match['name']}."
        try:
            face_client.watch([match["patient_id"]])
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
        frame = self.reader.latest_bgr() if self.reader is not None else None
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

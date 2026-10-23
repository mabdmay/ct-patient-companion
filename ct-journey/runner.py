"""Background thread that walks the journey graph (see stages.py). Every stage blocks until
a button is pressed in the UI - `advance(choice)` - and the pressed button decides which
stage comes next. Nothing is on a timer.

It also owns the frame source (see camera_source.py - the laptop's own USB camera, the real
robot's camera via the ACU Gateway, or nothing at all) and, while a stage that asks for
sensing is on screen, either posts frames to the face-id service over HTTP (identify) or
runs the positioning library's pose checks on them directly (pose). Those results only
populate the on-screen status badges: they never advance a stage and never rewrite the
script's lines. With no camera (source "none", today's default while the camera is down) the
journey runs exactly the same, just without the badges - the operator's button presses stand
in for what the camera would have seen.
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
from pose_bridge import PoseBridge
from state import JourneyState

sys.path.insert(0, str(journey_config.FACE_ID_REPO))
from patient_id.gateway import GatewayClient  # noqa: E402

POLL_INTERVAL = 0.5
JPEG_QUALITY = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
# Stages where the live camera feed is worth putting on screen next to Olaf's face (only
# ever when a camera actually exists - see _run_stage).
CAMERA_PANEL_KINDS = ("identify", "pose")


class JourneyRunner(threading.Thread):
    def __init__(self, state: JourneyState, camera_index: int | None = None,
                 camera_source_choice: str = "none", robot_id: str | None = None):
        super().__init__(daemon=True)
        self.state = state
        self.camera_index = camera_index if camera_index is not None else journey_config.CAMERA_INDEX
        self.camera_source_choice = camera_source_choice
        self.robot_id_override = robot_id
        self.pose_bridge = PoseBridge()
        self.reader = None  # a camera_source.LocalCameraSource / RobotCameraSource, or None
        self.gateway = GatewayClient(journey_config.GATEWAY_URL, journey_config.ROBOT_DEVICE_ID)
        self._workflow_seq = itertools.count(1)
        self._last_pushed_text = None
        self._last_pushed_at = 0.0
        self._stop = threading.Event()
        self._next_event = threading.Event()
        self._chosen = 0  # index into the current stage's choices, set by advance()
        # "ask" means: don't touch any camera until the UI's pre-connect screen tells us
        # which source to use (see choose_camera_source / server.py POST /api/camera-source).
        # Any concrete choice - including "none" - resolves this immediately instead.
        self._source_chosen = threading.Event()
        if camera_source_choice != "ask":
            self._source_chosen.set()

    def stop(self) -> None:
        self._stop.set()
        self._next_event.set()
        self._source_chosen.set()  # unblock a run() still waiting on a source choice
        if self.reader is not None:
            self.reader.stop()

    def advance(self, choice: int = 0) -> None:
        """Called from the UI's stage buttons: `choice` is the index of the button pressed
        in the current stage's `choices`."""
        self._chosen = choice
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
        self._source_chosen.wait()
        if self._stop.is_set():
            return
        if self.camera_source_choice == "none":
            resolved_source, resolved_robot_id = "none", None
        else:
            self.reader, resolved_source, resolved_robot_id = camera_source.build_camera_source(
                self.camera_source_choice, self.camera_index, state=self.state,
                robot_id=self.robot_id_override)
            if not self.reader.ok:
                self.reader = None
        self.state.update(camera_source=resolved_source, robot_id=resolved_robot_id)

        stage_id = stages_mod.START
        while not self._stop.is_set():
            stage = stages_mod.by_id(stage_id)
            choice_index = self._run_stage(stage)
            if self._stop.is_set():
                return
            stage_id = stage.choices[choice_index].next
            if stage_id == stages_mod.START:
                self.state.reset_patient()  # looping round for the next appointment

    def _camera_available(self) -> bool:
        return self.reader is not None

    def _push_to_robot(self, title: str, text: str) -> None:
        """Mirror the current instruction onto the real robot's screen (no-op/dry-run until
        journey_config.GATEWAY_URL and ROBOT_DEVICE_ID are set). Throttled and deduped so a
        fast-changing local message doesn't flood the shared gateway with new workflows."""
        if not text or text == self._last_pushed_text:
            return
        now = time.monotonic()
        if now - self._last_pushed_at < journey_config.GATEWAY_MIN_INTERVAL_S:
            return
        self._last_pushed_text = text
        self._last_pushed_at = now
        workflow_id = f"ct-journey-{next(self._workflow_seq)}"

        def push():
            try:
                self.gateway.publish_screen(workflow_id, title, text)
            except (RuntimeError, requests.exceptions.RequestException) as exc:
                # A gateway hiccup (bad HTTP response, or - as happened here - the gateway
                # being completely unreachable: connect timeout/refused) must never kill the
                # journey. It used to: gateway._call() raises plain RuntimeError for HTTP
                # errors but lets requests' own network exceptions (ConnectTimeout etc.)
                # propagate uncaught, which silently killed the whole journey loop while the
                # HTTP API stayed up - advance() kept returning {"ok": true} with nothing
                # left alive to read it.
                print(f"[journey] gateway push failed: {exc}")

        # Fire-and-forget: an unreachable gateway takes its full connect timeout to fail, and
        # the journey thread must not spend that staring past a button press.
        threading.Thread(target=push, daemon=True).start()

    def _capture_jpeg(self) -> bytes | None:
        if self.reader is None:
            return None
        return self.reader.latest_jpeg()

    def _run_stage(self, stage) -> int:
        """Show a stage and block until one of its buttons is pressed; returns that button's
        index. Background sensing (when a camera exists) runs on every tick of the wait."""
        message = stages_mod.render_message(stage, self.state, journey_config)
        camera_ready = self._camera_available()
        # Armed before the new stage goes on screen, so a press that lands the instant it
        # appears still counts for it rather than being cleared away underneath.
        self._chosen = 0
        self._next_event.clear()
        self.state.enter_stage(stage, message, [c.label for c in stage.choices])
        self._push_to_robot(stage.title, message)

        self.state.update(example_images=journey_config.POSE_EXAMPLE_IMAGE_NAMES if stage.kind == "examples" else [])
        if stage.kind != "pose":
            self.state.update(posture_status=None, posture_reasons=[])
        if stage.kind != "identify":
            self.state.update(face_aligned=None, track_status=None)
        self.state.update(watching=camera_ready and stage.kind in CAMERA_PANEL_KINDS)
        if self.reader is not None:
            self.reader.show_raw = stage.kind != "pose"

        # wait() rather than sleep(): a button press moves the journey on at once instead of
        # after up to a full sensing tick.
        while not self._next_event.wait(POLL_INTERVAL) and not self._stop.is_set():
            if camera_ready:
                if stage.kind == "identify":
                    self._identify_tick(stage.id)
                elif stage.kind == "pose":
                    self._pose_tick()
        self._next_event.clear()
        chosen = self._chosen
        return chosen if 0 <= chosen < len(stage.choices) else 0

    def _face_aligned(self, box: list[float], frame) -> bool:
        """True once a detected face's box is centered and large enough inside the on-screen
        alignment guide - so what the patient sees lines up with what actually counts as a
        usable look at them."""
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
        """One identify attempt against the live camera, for the status badge and the
        greeting's name only - the stage still advances on a button press either way.

        The first identification (waiting room) auto-selects whichever registered patient
        is actually in frame (anyone in patients.json). Every later "confirm it is still
        you" stage then locks onto that same patient_id, so a different registered person
        wandering into frame later is never mistaken for them.
        """
        jpeg = self._capture_jpeg()
        if jpeg is None:
            return False
        try:
            faces = face_client.identify_bytes(jpeg)
        except requests.RequestException as exc:
            print(f"[journey] identify failed: {exc}")
            return False
        expected_id = journey_config.DEMO_PATIENT_ID if stage_id in ("call_first", "call_again") \
            else self.state.detected_patient_id
        match = face_client.best_match(faces, expected_id)
        if not match:
            self.state.update(face_aligned=False)
            return False
        aligned = self._face_aligned(match["box"], self.reader.latest_bgr() if self.reader else None)
        self.state.update(face_aligned=aligned)
        if not aligned:
            return False  # known face seen, but not yet centered/close enough
        self.state.update(detected_name=match["name"], detected_patient_id=match["patient_id"],
                          detected_score=match["score"])
        try:
            face_client.watch([match["patient_id"]])
        except requests.RequestException:
            pass
        return True

    def _pose_tick(self) -> None:
        """Pose assessment for the badge and the annotated preview frame. It deliberately
        does NOT rewrite Olaf's line: at the CT table the script's own correction wording is
        used, and which branch of it to take is the operator's button press."""
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

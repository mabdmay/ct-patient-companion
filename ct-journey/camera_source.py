"""Where the orchestrator's frames come from: either the laptop's own USB camera (today's
default - what the whole demo has been built and tested against), or the real robot's own
cameras via the ACU Gateway, once an actual robot is registered with it. Both sources expose
the same small interface so runner.py doesn't care which one it's using.
"""
import threading
import time

import cv2
import requests

import journey_config

JPEG_QUALITY = [int(cv2.IMWRITE_JPEG_QUALITY), 80]


class LocalCameraSource:
    """The laptop's own USB camera, read continuously in a background thread (today's
    default and the only source actually exercised so far). While `show_raw` is True, also
    keeps the UI's live preview updated; pose_monitoring turns that off so its own annotated
    overlay (written at the slower inference cadence) isn't instantly overwritten."""

    def __init__(self, camera_index: int, state=None):
        self.camera_index = camera_index
        self.state = state
        self.camera = None
        self._thread = None
        self._lock = threading.Lock()
        self._frame = None  # latest decoded BGR frame
        self._stop = threading.Event()
        self.show_raw = True
        self.ok = False

    def start(self) -> bool:
        self.camera = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        self.ok = self.camera.isOpened()
        if self.ok:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self.ok

    def _run(self) -> None:
        while not self._stop.is_set():
            ok, frame = self.camera.read()
            if not ok:
                time.sleep(0.03)
                continue
            with self._lock:
                self._frame = frame
            if self.show_raw and self.state is not None:
                ok, buf = cv2.imencode(".jpg", frame, JPEG_QUALITY)
                if ok:
                    self.state.set_camera_frame(buf.tobytes())

    def latest_bgr(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def latest_jpeg(self) -> bytes | None:
        frame = self.latest_bgr()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame, JPEG_QUALITY)
        return buf.tobytes() if ok else None

    def stop(self) -> None:
        self._stop.set()
        if self.camera is not None:
            self.camera.release()


class RobotCameraSource:
    """The real robot's own camera, polled from the ACU Gateway's
    /api/acu/robots/{robotId}/cameras/{which}/latest endpoint instead of a local device."""

    def __init__(self, gateway_url: str, robot_id: str, which: str = "front", poll_interval: float = 0.15, state=None):
        self.gateway_url = gateway_url.rstrip("/")
        self.robot_id = robot_id
        self.which = which
        self.poll_interval = poll_interval
        self.state = state
        self._thread = None
        self._lock = threading.Lock()
        self._jpeg = None
        self._stop = threading.Event()
        self.show_raw = True
        self.ok = False

    def start(self) -> bool:
        # Confirm the endpoint actually yields a frame before committing to this source -
        # the robot may be registered but not yet streaming (503 "no frame in 10s").
        url = f"{self.gateway_url}/api/acu/robots/{self.robot_id}/cameras/{self.which}/latest"
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200 and r.content:
                with self._lock:
                    self._jpeg = r.content
                self.ok = True
        except requests.RequestException:
            self.ok = False
        if self.ok:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self.ok

    def _run(self) -> None:
        url = f"{self.gateway_url}/api/acu/robots/{self.robot_id}/cameras/{self.which}/latest"
        while not self._stop.is_set():
            try:
                r = requests.get(url, timeout=3)
                if r.status_code == 200 and r.content:
                    with self._lock:
                        self._jpeg = r.content
                    if self.show_raw and self.state is not None:
                        self.state.set_camera_frame(r.content)
            except requests.RequestException:
                pass
            time.sleep(self.poll_interval)

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    def latest_bgr(self):
        jpeg = self.latest_jpeg()
        if jpeg is None:
            return None
        import numpy as np
        arr = np.frombuffer(jpeg, dtype="uint8")
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def stop(self) -> None:
        self._stop.set()


def list_robot_devices(gateway_url: str) -> list[dict]:
    """Whatever robots are currently registered with the ACU Gateway (usually empty until
    the physical robot itself connects - this orchestrator never registers one, it only
    consumes an already-connected robot's feed)."""
    try:
        r = requests.get(f"{gateway_url.rstrip('/')}/api/acu/devices", timeout=4)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as exc:
        print(f"[camera_source] could not list gateway devices: {exc}")
        return []


def build_camera_source(choice: str, camera_index: int, state=None, robot_id: str | None = None):
    """Builds and starts the chosen source, falling back to the local camera (with a clear
    warning) if "robot" was requested but no usable robot camera is actually available -
    a live demo should never just hang waiting for hardware that isn't there."""
    if choice == "robot":
        rid = robot_id
        if not rid:
            devices = list_robot_devices(journey_config.GATEWAY_URL)
            online = [d for d in devices if isinstance(d, dict) and d.get("deviceId")]
            if len(online) == 1:
                rid = online[0]["deviceId"]
            elif len(online) > 1:
                print(f"[camera_source] multiple robots registered ({[d['deviceId'] for d in online]}); "
                      "pass one explicitly with --robot-id. Falling back to the local camera.")
            else:
                print("[camera_source] no robot is currently registered with the ACU Gateway. "
                      "Falling back to the local camera.")
        if rid:
            source = RobotCameraSource(journey_config.GATEWAY_URL, rid, state=state)
            if source.start():
                print(f"[camera_source] using robot '{rid}' front camera via the ACU Gateway")
                return source, "robot", rid
            print(f"[camera_source] robot '{rid}' is registered but its camera isn't streaming "
                  "(no frame in the last check). Falling back to the local camera.")

    source = LocalCameraSource(camera_index, state=state)
    started = source.start()
    if not started:
        print(f"[camera_source] warning: local camera {camera_index} did not open")
    return source, "external", None

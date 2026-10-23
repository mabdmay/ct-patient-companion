"""Launch the whole patient-journey demo:
  1. starts patient-face-id-robot's patient_id.service as a subprocess, with no camera of its
     own - this orchestrator owns the one physical camera and posts frames to it over HTTP;
  2. starts this project's background JourneyRunner, which walks the journey graph
     (stages.py) one button press at a time;
  3. serves the on-screen UI (web/) over local HTTP for a browser to open.

The journey is entirely button-driven: each phase of patient-journey-script.md stays on
screen until someone presses the button for what just happened in the room, and the branch
points (did the patient change? is the pose good?) offer a button each.

Usage:
    python run.py                             # no camera - the buttons stand in for it (default)
    python run.py --camera-source external    # also use the laptop's USB camera for sensing
    python run.py --camera-source external --camera 0   # ...if it isn't at index 1
    python run.py --camera-source robot [--robot-id <deviceId>]   # the robot's own cameras
    python run.py --camera-source ask         # pick the source from a screen in the UI
    python run.py --no-face-service           # if patient_id.service is already running elsewhere

A camera, when present, only drives the status badges and the live preview panel; it never
advances a stage. With the default "none" the journey runs the same way, minus the badges.
"""
import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests
import uvicorn

import journey_config
from runner import JourneyRunner
from server import create_app
from state import JourneyState


def start_face_service() -> subprocess.Popen:
    cmd = [sys.executable, "-m", "patient_id.service", "--port", str(journey_config.FACE_SERVICE_PORT)]
    return subprocess.Popen(cmd, cwd=str(journey_config.FACE_ID_REPO))


def start_kokoro_service() -> subprocess.Popen | None:
    """Local free TTS fallback - a separate Python 3.12 venv since `kokoro` needs <3.13.
    Missing venv (not set up on this machine) is a soft skip, not an error: ElevenLabs and
    the browser's own voice still cover Olaf's speech either way."""
    python = journey_config.KOKORO_VENV_PYTHON
    if not python.exists():
        print(f"[journey] kokoro venv not found at {python}; skipping local TTS fallback")
        return None
    cmd = [str(python), "kokoro_service.py", "--port", str(journey_config.KOKORO_SERVICE_PORT)]
    return subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent))


def wait_for_service(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{url}/health", timeout=1).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the full CT patient journey demo")
    ap.add_argument("--camera", type=int, default=journey_config.CAMERA_INDEX,
                     help="camera index this orchestrator captures from (default %(default)s)")
    ap.add_argument("--no-face-service", action="store_true", help="assume patient_id.service is already running")
    ap.add_argument("--camera-source", choices=["none", "external", "robot", "ask"], default="none",
                     help="frame source for the optional background sensing: none (default - the "
                          "buttons stand in for the camera), this laptop's camera, the real robot's "
                          "camera via the ACU Gateway, or a choice screen in the UI")
    ap.add_argument("--robot-id", default=None,
                     help="which registered robot to use with --camera-source robot (auto-picked if only one is online)")
    args = ap.parse_args()

    face_proc = None
    # Nothing to identify against without a camera, so don't pay the service's startup cost.
    if not args.no_face_service and args.camera_source != "none":
        print("[journey] starting patient_id.service (frames arrive over HTTP; no camera of its own) ...")
        face_proc = start_face_service()
        if wait_for_service(journey_config.FACE_SERVICE_URL):
            print("[journey] face-id service ready")
        else:
            print("[journey] face-id service did not come up in time; continuing anyway")

    kokoro_proc = start_kokoro_service()
    if kokoro_proc is not None:
        print("[journey] starting kokoro TTS service ...")
        if wait_for_service(journey_config.KOKORO_SERVICE_URL, timeout=60.0):
            print("[journey] kokoro TTS service ready")
        else:
            print("[journey] kokoro TTS service did not come up in time; ElevenLabs/browser voice will be used instead")

    state = JourneyState()
    runner = JourneyRunner(state, camera_index=args.camera,
                            camera_source_choice=args.camera_source, robot_id=args.robot_id)
    runner.start()

    app = create_app(state, runner)
    # JOURNEY_HOST is 0.0.0.0 so the robot's panel and a phone on the same wifi can reach
    # this - but 0.0.0.0 is not an address a browser can open, so print ones that are: this
    # machine, and the LAN address other devices use.
    port = journey_config.JOURNEY_PORT
    print(f"[journey] UI at http://localhost:{port}")
    lan_ip = socket.gethostbyname(socket.gethostname())
    if lan_ip and not lan_ip.startswith("127."):
        print(f"[journey]    from another device on this network: http://{lan_ip}:{port}")
    try:
        uvicorn.run(app, host=journey_config.JOURNEY_HOST, port=journey_config.JOURNEY_PORT, log_level="warning")
    finally:
        runner.stop()
        if face_proc is not None:
            face_proc.terminate()
        if kokoro_proc is not None:
            kokoro_proc.terminate()


if __name__ == "__main__":
    main()

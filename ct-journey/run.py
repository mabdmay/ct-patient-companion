"""Launch the whole patient-journey demo:
  1. starts patient-face-id-robot's patient_id.service as a subprocess, with no camera of its
     own - this orchestrator owns the one physical camera and posts frames to it over HTTP;
  2. starts this project's background JourneyRunner, which advances the journey stages and
     drives both the face-id HTTP API and the positioning repo's pose checks (imported
     directly) using frames from that one camera;
  3. serves the on-screen UI (web/) over local HTTP for a browser to open.

Usage:
    python run.py --manual              # click 'Next' in the UI to advance; real camera used
    python run.py --manual --camera 0   # if the USB camera isn't at index 1
    python run.py                       # fully automatic, timer-driven stages
    python run.py --no-face-service     # if patient_id.service is already running elsewhere

Camera source (external USB camera vs. the real robot's own cameras over the ACU Gateway) is
chosen from the UI itself by default: the web page shows an "External camera / Robot
cameras" screen before the journey starts, and nothing touches a camera until that choice is
made there - see web/index.html and POST /api/camera-source. Pass --camera-source to skip
that screen and start immediately (handy for testing):
    python run.py --camera-source external
    python run.py --camera-source robot [--robot-id <deviceId>]
"""
import argparse
import subprocess
import sys
import time

import requests
import uvicorn

import journey_config
from runner import JourneyRunner
from server import create_app
from state import JourneyState


def start_face_service() -> subprocess.Popen:
    cmd = [sys.executable, "-m", "patient_id.service", "--port", str(journey_config.FACE_SERVICE_PORT)]
    return subprocess.Popen(cmd, cwd=str(journey_config.FACE_ID_REPO))


def wait_for_face_service(timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(f"{journey_config.FACE_SERVICE_URL}/health", timeout=1).ok:
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
    ap.add_argument("--manual", action="store_true",
                     help="click 'Next' in the UI to advance stages instead of a fixed timer")
    ap.add_argument("--camera-source", choices=["external", "robot", "ask"], default="ask",
                     help="frame source: this laptop's camera, the real robot's camera via the ACU Gateway, "
                          "or prompt at startup (default)")
    ap.add_argument("--robot-id", default=None,
                     help="which registered robot to use with --camera-source robot (auto-picked if only one is online)")
    args = ap.parse_args()

    face_proc = None
    if not args.no_face_service:
        print("[journey] starting patient_id.service (frames arrive over HTTP; no camera of its own) ...")
        face_proc = start_face_service()
        if wait_for_face_service():
            print("[journey] face-id service ready")
        else:
            print("[journey] face-id service did not come up in time; continuing anyway")

    state = JourneyState()
    runner = JourneyRunner(state, manual=args.manual, camera_index=args.camera,
                            camera_source_choice=args.camera_source, robot_id=args.robot_id)
    runner.start()

    app = create_app(state, runner)
    print(f"[journey] UI at http://{journey_config.JOURNEY_HOST}:{journey_config.JOURNEY_PORT}")
    try:
        uvicorn.run(app, host=journey_config.JOURNEY_HOST, port=journey_config.JOURNEY_PORT, log_level="warning")
    finally:
        runner.stop()
        if face_proc is not None:
            face_proc.terminate()


if __name__ == "__main__":
    main()

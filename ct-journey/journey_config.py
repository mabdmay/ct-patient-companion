"""Paths, camera indices and demo constants for the patient-journey orchestrator.

Wires together two existing, untouched repos:
  - patient-face-id-robot  (face recognition + continuous tracking; run as its own HTTP service)
  - hackathon-...-742      (the "CT_Patient_Positioning" repo; imported as a library for pose checks)

Override the camera index on the command line (see run.py --help); this is just the default.
"""
from pathlib import Path

OLAF = Path(__file__).resolve().parent.parent
FACE_ID_REPO = OLAF / "patient-face-id-robot"
POSITIONING_REPO = OLAF / "hackathon-20261022-191913-742"

# One physical USB camera, reused for both roles: this orchestrator owns it and (a) posts
# frames to patient_id.service over HTTP for identify/track, and (b) runs the positioning
# library's pose checks on it directly during pose_monitoring. Index 1 is what worked when
# this camera was tested earlier on this laptop (DirectShow, cv2.CAP_DSHOW).
CAMERA_INDEX = 1

FACE_SERVICE_HOST = "127.0.0.1"
FACE_SERVICE_PORT = 8080
FACE_SERVICE_URL = f"http://{FACE_SERVICE_HOST}:{FACE_SERVICE_PORT}"

# Local Kokoro-82M TTS microservice (free, open-weight, offline) - the middle tier of the
# voice fallback chain (ElevenLabs -> Kokoro -> browser voice, see tts.py). Runs under its
# own Python 3.12 venv (kokoro_venv/) since `kokoro` needs Python <3.13.
KOKORO_VENV_PYTHON = OLAF / "ct-journey" / "kokoro_venv" / "Scripts" / "python.exe"
KOKORO_SERVICE_PORT = 8071
KOKORO_SERVICE_URL = f"http://127.0.0.1:{KOKORO_SERVICE_PORT}"

JOURNEY_HOST = "0.0.0.0"
JOURNEY_PORT = 8090

# Demo stands in for "today's worklist". A real deployment would get specific expected
# patients from the ACU schedule; here the robot instead accepts whoever it recognizes
# from patient-face-id-robot/data/patients.json (currently Abdullah and Taimoor) and
# greets them by name. None = no particular patient is expected at the call-out.
DEMO_PATIENT_ID = None

# Per the patient-journey script: the robot calls out the next appointment's name *before*
# it has identified anyone (from the day's schedule, in a real deployment). This is that
# stand-in - who the waiting-room call-out addresses by name. It does NOT restrict who can
# actually be recognized (any registered patient in patients.json still auto-matches, same
# as before) - it only changes what the robot says while still waiting for a face.
NEXT_APPOINTMENT_NAME = "Abdullah"

# The on-screen alignment guide shown over the live camera feed during face-identify
# stages: a face only "counts" for matching once it's centered and large enough inside this
# box, so the patient gets a moment to step into position before anything is confirmed.
# Expressed as fractions of the frame so it doesn't depend on camera resolution.
FACE_FRAME_MARGIN_X = 0.30   # guide box spans the middle (1 - 2*margin) of the frame width
FACE_FRAME_MARGIN_Y = 0.12   # ...and the middle (1 - 2*margin) of the frame height
FACE_FRAME_MIN_WIDTH_FRAC = 0.16  # detected face box must be at least this wide (relative to frame) to count as "close enough"

POSE_MODEL_WEIGHTS = POSITIONING_REPO / "yolo26n-pose.pt"

# Frames 8 and 9 from the supplied-photo review (outputs/data_review.csv): both scored
# WITHIN_CRITERIA, ALONGSIDE_BODY arms - the reference "ideal position" shown to the patient.
POSE_EXAMPLE_DIR = POSITIONING_REPO / "outputs" / "data_review"
POSE_EXAMPLE_IMAGE_NAMES = ["0008.png", "0009.png"]

# -- ACU API Gateway (docs at GATEWAY_URL + "/docs/index.html"): pushes the journey's
# narration to the physical robot's screen + TTS, and (once a robot is registered with it)
# can source live frames from the robot's own cameras instead of the laptop's USB camera -
# see camera_source.py / run.py --camera-source robot. Empty url = dry-run (prints what it
# would send, sends nothing). ROBOT_DEVICE_ID stays empty until a real robot shows up in
# GET /api/acu/devices - never guess it; `--camera-source robot` will pick it up
# automatically if exactly one device is registered, or pass --robot-id explicitly.
GATEWAY_URL = "http://10.27.239.122:3000"  # no trailing /api
ROBOT_DEVICE_ID = ""       # your organizer-approved device, e.g. "team-blue-01" - set once one is registered
GATEWAY_MIN_INTERVAL_S = 2.5  # don't push a new workflow to the shared gateway more often than this

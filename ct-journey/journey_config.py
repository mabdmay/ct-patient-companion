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

JOURNEY_HOST = "0.0.0.0"
JOURNEY_PORT = 8090

# Demo stands in for "today's worklist". A real deployment would get specific expected
# patients from the ACU schedule; here the robot instead accepts whoever it recognizes
# from patient-face-id-robot/data/patients.json (currently Abdullah and Taimoor) and
# greets them by name. DEMO_PATIENT_NAME is only a fallback for the brief window before
# anyone has been identified yet.
DEMO_PATIENT_ID = None
DEMO_PATIENT_NAME = "there"

# Placeholder timings until the robot's real navigation is wired in - a "travel" stage
# (guide_changing_room, guide_ct_room, return_waiting_room) just holds for this long to
# simulate the walk; swap in a per-route estimate from the real router later.
SIMULATED_TRAVEL_SECONDS = 4.0

# Extra breathing room on top of a successful face match in the "confirm it's still you"
# stages, so the robot doesn't snap straight to the next stage the instant it recognizes
# someone - it lingers a little on the confirmation itself.
CONFIRM_DWELL_SECONDS = 3.0

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

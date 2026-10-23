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

JOURNEY_HOST = "127.0.0.1"
JOURNEY_PORT = 8090

# Demo stands in for "today's worklist": which registered patient the robot is expecting.
# A real deployment would get this from the ACU schedule, not a hardcoded id.
DEMO_PATIENT_ID = "abdullah"
DEMO_PATIENT_NAME = "Abdullah"

POSE_MODEL_WEIGHTS = POSITIONING_REPO / "yolo26n-pose.pt"

# Frames 8 and 9 from the supplied-photo review (outputs/data_review.csv): both scored
# WITHIN_CRITERIA, ALONGSIDE_BODY arms - the reference "ideal position" shown to the patient.
POSE_EXAMPLE_DIR = POSITIONING_REPO / "outputs" / "data_review"
POSE_EXAMPLE_IMAGE_NAMES = ["0008.png", "0009.png"]

# -- ACU API Gateway (hackathon-api-guide.pdf): pushes the journey's narration to the
# physical KettyBot Pro's screen + TTS. Empty url = dry-run (prints what it would send,
# sends nothing) - this can only be filled in with values the hackathon organizers give
# you on-site (gateway base URL, your approved device id). Never guess these.
GATEWAY_URL = ""           # e.g. "http://10.27.238.122:3000" (no trailing /api)
ROBOT_DEVICE_ID = ""       # your organizer-approved device, e.g. "team-blue-01"
GATEWAY_MIN_INTERVAL_S = 2.5  # don't push a new workflow to the shared gateway more often than this

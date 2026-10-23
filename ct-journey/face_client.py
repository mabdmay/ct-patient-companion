"""Thin HTTP client for the patient_id service (patient-face-id-robot/patient_id/service.py).

Treated as a black box behind its REST API - the same way a real ACU Gateway would call it -
so that repo needs no changes to be reused here.
"""
import requests

import journey_config

BASE = journey_config.FACE_SERVICE_URL
TIMEOUT = 4.0


def health():
    r = requests.get(f"{BASE}/health", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def snapshot_jpeg() -> bytes:
    r = requests.get(f"{BASE}/camera/snapshot.jpg", timeout=TIMEOUT)
    r.raise_for_status()
    return r.content


def identify_snapshot() -> list[dict]:
    """Grab the service's own camera frame and identify every face in it (service started
    with --camera; not used by the single-shared-camera path, kept for that deployment)."""
    jpeg = snapshot_jpeg()
    return identify_bytes(jpeg)


def identify_bytes(jpeg: bytes) -> list[dict]:
    """Identify every face in a JPEG this orchestrator captured itself."""
    r = requests.post(f"{BASE}/identify", data=jpeg, headers={"Content-Type": "image/jpeg"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["faces"]


def track_frame_bytes(jpeg: bytes) -> dict:
    """Post one frame for continuous tracking; same response shape as track_status()."""
    r = requests.post(f"{BASE}/track/frame", data=jpeg, headers={"Content-Type": "image/jpeg"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def best_match(faces: list[dict], expected_patient_id: str | None = None) -> dict | None:
    """Highest-scoring known face. When an expected id is given (today's worklist), only
    that specific patient counts as a match - someone else recognized in frame (even a
    registered patient) must never be treated as the one the robot is waiting for."""
    known = [f for f in faces if f["patient_id"]]
    if not known:
        return None
    if expected_patient_id:
        return next((f for f in known if f["patient_id"] == expected_patient_id), None)
    return max(known, key=lambda f: f["score"])


def watch(patient_ids: list[str]) -> dict:
    r = requests.post(f"{BASE}/track/watch", json={"patient_ids": patient_ids}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def track_status() -> dict:
    r = requests.get(f"{BASE}/track/status", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def clear_watch() -> None:
    requests.delete(f"{BASE}/track/watch", timeout=TIMEOUT)

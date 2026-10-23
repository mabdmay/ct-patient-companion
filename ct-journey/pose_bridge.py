"""Bridge to the positioning repo's library code (imported, not modified or copied).

Builds a frame-spanning table calibration so the pipeline runs against whatever ceiling
camera is plugged in for the demo, without a real surveyed CT-bed calibration.

DEMONSTRATION PLACEHOLDER: a production deployment must replace TABLE_CORNERS with a real
measured bed calibration (see that repo's README, "Table Setup") - this one just treats the
whole frame as the table so the journey demo is runnable on any camera angle.
"""
import sys
import threading

import numpy as np

import journey_config

sys.path.insert(0, str(journey_config.POSITIONING_REPO))

from positioning.arms import ArmRules          # noqa: E402
from positioning.calibration import TableCalibration  # noqa: E402
from positioning.geometry import assess_position      # noqa: E402
from positioning.perception import YoloPoseBackend     # noqa: E402
from positioning.types import Rules                     # noqa: E402
from positioning.visualization import annotate          # noqa: E402

MODEL_CONFIG = {
    "weights": str(journey_config.POSE_MODEL_WEIGHTS),
    "device": "cpu",
    "image_size": 640,
    "confidence": 0.35,
    "cpu_threads": 4,
}

TABLE_CORNERS = [[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]]

RULES = Rules(
    min_detection_confidence=0.35,
    min_keypoint_confidence=0.5,
    min_torso_length_fraction=0.04,
    reference_x_fraction=0.0,
    reference_y_fraction=None,
    reference_axis_deg=0.0,
    max_lateral_fraction=0.12,
    max_angle_deg=12.0,
    max_longitudinal_fraction=0.15,
    arm_rules=ArmRules(allowed_postures=("ALONGSIDE_BODY", "OVER_TORSO"), min_confidence=0.5),
)


class PoseBridge:
    """Loads the YOLO pose model once; call assess_and_annotate(frame) per frame."""

    def __init__(self):
        self._lock = threading.Lock()
        self._backend = None

    def _ensure_loaded(self):
        if self._backend is None:
            with self._lock:
                if self._backend is None:
                    self._backend = YoloPoseBackend(MODEL_CONFIG, journey_config.POSITIONING_REPO, TABLE_CORNERS)

    def assess_and_annotate(self, frame: np.ndarray):
        self._ensure_loaded()
        table = TableCalibration(TABLE_CORNERS, frame.shape, confirmed=True, near_nadir=True, dimensions_cm=None)
        with self._lock:
            detections = self._backend.detect(frame)
            assessment = assess_position(detections, table, RULES)
            rendered = annotate(frame, detections, table, RULES, assessment, 0.0, False)
        return assessment, rendered

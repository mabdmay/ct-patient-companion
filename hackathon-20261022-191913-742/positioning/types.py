from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from positioning.arms import ArmRules


class Status(str, Enum):
    WITHIN_CRITERIA = "WITHIN_CRITERIA"
    REPOSITION_REQUIRED = "REPOSITION_REQUIRED"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class PoseDetection:
    box: np.ndarray
    confidence: float
    keypoints: np.ndarray


@dataclass
class Assessment:
    status: Status
    reasons: list[str]
    measurements: dict[str, float] = field(default_factory=dict)
    perception_confidence: float | None = None
    torso_points: np.ndarray | None = None
    detection: PoseDetection | None = None
    arm_assessment: dict | None = None


@dataclass(frozen=True)
class Rules:
    min_detection_confidence: float = 0.35
    min_keypoint_confidence: float = 0.5
    min_torso_length_fraction: float = 0.04
    reference_x_fraction: float = 0.0
    reference_y_fraction: float | None = None
    reference_axis_deg: float = 0.0
    max_lateral_fraction: float = 0.08
    max_angle_deg: float = 8.0
    max_longitudinal_fraction: float = 0.1
    arm_rules: "ArmRules | None" = None
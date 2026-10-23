from dataclasses import dataclass

import numpy as np

from positioning.types import Status


POSTURES = {"ARMS_RAISED", "ALONGSIDE_BODY", "OVER_TORSO", "MIXED"}


@dataclass(frozen=True)
class ArmRules:
    allowed_postures: tuple[str, ...] | None = None
    min_confidence: float = 0.5
    raised_wrist_margin: float = 0.15
    raised_elbow_limit: float = 0.2
    torso_wrist_lateral_limit: float = 0.45
    torso_inward_margin: float = 0.15
    torso_wrist_longitudinal_max: float = 0.95
    alongside_wrist_lateral_min: float = 0.35
    alongside_wrist_longitudinal_min: float = 0.55
    max_segment_length: float = 1.25


@dataclass
class ArmAssessment:
    posture: str
    left: str
    right: str
    confidence: float | None
    status: Status | None
    reasons: list[str]
    measurements: dict[str, float]
    allowed_postures: tuple[str, ...] | None = None

    def as_dict(self) -> dict:
        return {
            "posture": self.posture, "left": self.left, "right": self.right,
            "confidence": self.confidence,
            "policy_enabled": self.status is not None,
            "allowed_postures": None if self.allowed_postures is None else list(self.allowed_postures),
            "status": None if self.status is None else self.status.value,
            "reasons": self.reasons, "measurements": self.measurements,
        }


def assess_arms(keypoints: np.ndarray, rules: ArmRules) -> ArmAssessment:
    enabled = rules.allowed_postures is not None

    def uncertain(reason):
        return ArmAssessment("UNCERTAIN", "UNCERTAIN", "UNCERTAIN", None,
                             Status.UNCERTAIN if enabled else None, [reason], {}, rules.allowed_postures)

    indices = [5, 6, 7, 8, 9, 10, 11, 12]
    if keypoints.shape != (17, 3):
        return uncertain("missing_arm_landmarks")
    required = keypoints[indices]
    if not np.isfinite(required).all() or np.any(required[:, 2] < rules.min_confidence) or np.any(required[:, 2] > 1):
        return uncertain("low_or_invalid_arm_confidence")
    shoulders = keypoints[[5, 6], :2]
    hips = keypoints[[11, 12], :2]
    origin = shoulders.mean(axis=0)
    axis = hips.mean(axis=0) - origin
    length = float(np.linalg.norm(axis))
    if length < 1e-6:
        return uncertain("degenerate_arm_reference_geometry")
    longitudinal = axis / length
    lateral = np.array([longitudinal[1], -longitudinal[0]])
    shoulder_width = abs(float((shoulders[1] - shoulders[0]) @ lateral))
    if shoulder_width / length < 0.15:
        return uncertain("insufficient_projected_shoulder_width")
    measurements = {}
    labels = []
    for name, shoulder_index, elbow_index, wrist_index in [("left", 5, 7, 9), ("right", 6, 8, 10)]:
        shoulder, elbow, wrist = keypoints[[shoulder_index, elbow_index, wrist_index], :2]
        segments = [np.linalg.norm(elbow - shoulder) / length, np.linalg.norm(wrist - elbow) / length]
        if min(segments) < 0.08 or max(segments) > rules.max_segment_length:
            return uncertain("implausible_projected_arm_geometry")
        elbow_long = float((elbow - origin) @ longitudinal / length)
        wrist_long = float((wrist - origin) @ longitudinal / length)
        elbow_side = abs(float((elbow - origin) @ lateral / shoulder_width))
        wrist_side = abs(float((wrist - origin) @ lateral / shoulder_width))
        measurements.update({f"{name}_wrist_longitudinal": wrist_long,
                             f"{name}_wrist_lateral_abs": wrist_side,
                             f"{name}_elbow_longitudinal": elbow_long,
                             f"{name}_elbow_lateral_abs": elbow_side})
        if wrist_long <= -rules.raised_wrist_margin and elbow_long <= rules.raised_elbow_limit:
            label = "ARMS_RAISED"
        elif (-0.15 <= wrist_long <= rules.torso_wrist_longitudinal_max
              and wrist_side <= rules.torso_wrist_lateral_limit
              and -0.2 <= elbow_long <= 1.2 and elbow_side <= 1.2
              and (wrist_long < elbow_long - 0.05 or wrist_side < elbow_side - rules.torso_inward_margin)):
            label = "OVER_TORSO"
        elif (rules.alongside_wrist_longitudinal_min <= wrist_long <= 1.8
              and rules.alongside_wrist_lateral_min <= wrist_side <= 1.5
              and -0.05 <= elbow_long <= 1.5 and elbow_side <= 1.5):
            label = "ALONGSIDE_BODY"
        else:
            label = "UNCERTAIN"
        labels.append(label)
    posture = labels[0] if labels[0] == labels[1] else "MIXED"
    if "UNCERTAIN" in labels:
        posture = "UNCERTAIN"
    reasons = ["arm_geometry_unclassified"] if posture == "UNCERTAIN" else ["arm_posture_observed"]
    status = None
    if enabled:
        if posture == "UNCERTAIN":
            status = Status.UNCERTAIN
        elif posture in rules.allowed_postures:
            status = Status.WITHIN_CRITERIA
            reasons = ["arm_posture_allowed"]
        else:
            status = Status.REPOSITION_REQUIRED
            reasons = ["arm_posture_not_allowed"]
    return ArmAssessment(posture, *labels, float(required[:, 2].min()), status, reasons, measurements, rules.allowed_postures)
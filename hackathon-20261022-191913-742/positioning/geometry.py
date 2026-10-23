import numpy as np

from positioning.arms import ArmRules, assess_arms
from positioning.calibration import TableCalibration
from positioning.types import Assessment, PoseDetection, Rules, Status


TORSO_INDICES = [5, 6, 11, 12]


def assess_position(
    detections: list[PoseDetection], table: TableCalibration, rules: Rules
) -> Assessment:
    if table.quality_reason:
        return Assessment(Status.UNCERTAIN, [table.quality_reason])
    candidates = []
    for detection in detections:
        if not np.isfinite(detection.confidence) or not 0 <= detection.confidence <= 1:
            return Assessment(Status.UNCERTAIN, ["invalid_detection"])
        if detection.confidence < rules.min_detection_confidence:
            continue
        if detection.box.shape != (4,) or not np.isfinite(detection.box).all():
            return Assessment(Status.UNCERTAIN, ["invalid_detection"])
        if table.intersects_box(detection.box):
            if detection.keypoints.shape == (17, 3):
                torso = detection.keypoints[TORSO_INDICES]
                if np.isfinite(torso).all() and np.all(torso[:, 2] >= rules.min_keypoint_confidence):
                    if not table.contains(torso[:, :2].mean(axis=0, keepdims=True)):
                        continue
            candidates.append(detection)
    if len(candidates) != 1:
        reason = "no_patient_on_table" if not candidates else "ambiguous_multiple_people"
        return Assessment(Status.UNCERTAIN, [reason])
    patient = candidates[0]
    keypoints = patient.keypoints
    if keypoints.shape != (17, 3):
        return Assessment(Status.UNCERTAIN, ["missing_pose_landmarks"], detection=patient)
    torso = keypoints[TORSO_INDICES]
    if not np.isfinite(torso).all() or np.any(torso[:, 2] < rules.min_keypoint_confidence) or np.any(torso[:, 2] > 1):
        return Assessment(Status.UNCERTAIN, ["low_or_invalid_landmark_confidence"], detection=patient)
    confidence = float(min(patient.confidence, torso[:, 2].min()))
    if not table.contains(torso[:, :2]):
        return Assessment(Status.UNCERTAIN, ["torso_landmarks_outside_table"], perception_confidence=confidence, detection=patient)
    points = table.transform(torso[:, :2])
    shoulders = points[:2].mean(axis=0)
    hips = points[2:].mean(axis=0)
    center = (shoulders + hips) / 2
    axis = hips - shoulders
    if not np.isfinite(points).all() or np.linalg.norm(axis) / table.width < rules.min_torso_length_fraction:
        return Assessment(Status.UNCERTAIN, ["degenerate_torso_geometry"], perception_confidence=confidence, detection=patient)
    angle = float(np.degrees(np.arctan2(axis[0], axis[1])))
    error = (angle - rules.reference_axis_deg + 90) % 180 - 90
    offset = float(center[0] / table.width - rules.reference_x_fraction)
    measurements = {"center_offset_fraction": offset, "axis_error_deg": abs(error)}
    reasons = []
    if abs(offset) > rules.max_lateral_fraction + 1e-7:
        reasons.append("lateral_offset")
    if abs(error) > rules.max_angle_deg + 1e-5:
        reasons.append("axis_error")
    if rules.reference_y_fraction is not None:
        longitudinal = float(center[1] / table.length - rules.reference_y_fraction)
        measurements["longitudinal_offset_fraction"] = longitudinal
        if abs(longitudinal) > rules.max_longitudinal_fraction + 1e-7:
            reasons.append("longitudinal_offset")
    if table.metric:
        measurements["center_offset_cm_projected"] = offset * table.width
        if "longitudinal_offset_fraction" in measurements:
            measurements["longitudinal_offset_cm_projected"] = measurements["longitudinal_offset_fraction"] * table.length
    arm_points = keypoints.copy()
    frame_width, frame_height = table.frame_size
    visible = np.isfinite(arm_points[:, :2]).all(axis=1)
    visible &= (arm_points[:, 0] >= 0) & (arm_points[:, 0] < frame_width)
    visible &= (arm_points[:, 1] >= 0) & (arm_points[:, 1] < frame_height)
    arm_points[~visible, 2] = 0.0
    if np.any(visible):
        arm_points[visible, :2] = table.transform(arm_points[visible, :2])
    arms = assess_arms(arm_points, rules.arm_rules or ArmRules(min_confidence=rules.min_keypoint_confidence))
    status = Status.REPOSITION_REQUIRED if reasons else Status.WITHIN_CRITERIA
    if arms.status == Status.UNCERTAIN:
        status = Status.UNCERTAIN
        confidence = None
        reasons.extend(arms.reasons)
    elif arms.status == Status.REPOSITION_REQUIRED:
        status = Status.REPOSITION_REQUIRED
        reasons.extend(arms.reasons)
    if arms.status is not None and arms.confidence is not None and confidence is not None:
        confidence = min(confidence, arms.confidence)
    return Assessment(status, reasons or ["configured_2d_checks_passed"], measurements,
                      confidence, torso[:, :2], patient, arms.as_dict())
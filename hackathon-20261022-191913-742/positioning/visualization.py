import cv2
import numpy as np

from positioning.calibration import TableCalibration
from positioning.types import Assessment, PoseDetection, Rules, Status


COLORS = {
    Status.WITHIN_CRITERIA: (70, 210, 100),
    Status.REPOSITION_REQUIRED: (80, 100, 255),
    Status.UNCERTAIN: (0, 210, 255),
}
EDGES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]
PANEL_HEIGHT = 30 * 7 + 14


def annotate(
    frame: np.ndarray, detections: list[PoseDetection], table: TableCalibration,
    rules: Rules, assessment: Assessment, processing_ms: float, synthetic: bool = False,
) -> np.ndarray:
    mask = np.zeros(frame.shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, table.corners.astype(np.int32), 255)
    image = cv2.bitwise_and(frame, frame, mask=mask)
    cv2.polylines(image, [table.corners.astype(np.int32)], True, (230, 210, 50), 2)
    axis = table.to_image(np.array([[0, 0], [0, table.length]])).astype(int)
    cv2.line(image, tuple(axis[0]), tuple(axis[1]), (0, 230, 230), 2)
    reference_x = rules.reference_x_fraction * table.width
    tolerance = rules.max_lateral_fraction * table.width
    for lateral in [reference_x - tolerance, reference_x + tolerance]:
        line = table.to_image(np.array([[lateral, 0], [lateral, table.length]])).astype(int)
        cv2.line(image, tuple(line[0]), tuple(line[1]), (100, 150, 100), 1)
    reference_line = table.to_image(np.array([[reference_x, 0], [reference_x, table.length]])).astype(int)
    cv2.line(image, tuple(reference_line[0]), tuple(reference_line[1]), (240, 130, 200), 1)
    if rules.reference_y_fraction is not None:
        marker = table.to_image(np.array([[reference_x, rules.reference_y_fraction * table.length]]))[0].astype(int)
        cv2.drawMarker(image, tuple(marker), (240, 130, 200), cv2.MARKER_CROSS, 18, 2)
    for detection in ([assessment.detection] if assessment.detection is not None else []):
        keypoints = detection.keypoints
        if keypoints.shape != (17, 3):
            continue
        valid = np.isfinite(keypoints).all(axis=1) & (keypoints[:, 2] >= rules.min_keypoint_confidence) & (keypoints[:, 2] <= 1)
        for start, end in EDGES:
            if valid[start] and valid[end]:
                cv2.line(image, tuple(keypoints[start, :2].astype(int)), tuple(keypoints[end, :2].astype(int)), (220, 170, 100), 2)
        for point in keypoints[valid, :2]:
            cv2.circle(image, tuple(point.astype(int)), 4, (255, 240, 220), -1)
    if assessment.torso_points is not None:
        shoulders = assessment.torso_points[:2].mean(axis=0).astype(int)
        hips = assessment.torso_points[2:].mean(axis=0).astype(int)
        center = ((shoulders + hips) / 2).astype(int)
        cv2.line(image, tuple(shoulders), tuple(hips), COLORS[assessment.status], 4)
        cv2.drawMarker(image, tuple(center), COLORS[assessment.status], cv2.MARKER_CROSS, 22, 2)
    lines = [
        (assessment.status.value, COLORS[assessment.status]),
        ("ADVISORY ONLY | single-frame 2D checks | NOT scan authorization", (235, 235, 235)),
        (", ".join(assessment.reasons), (235, 235, 235)),
    ]
    if assessment.measurements:
        measurements = assessment.measurements
        lines.append((f"Lateral: {measurements['center_offset_fraction']:+.3f} table widths | Axis error: {measurements['axis_error_deg']:.1f} deg", (235, 235, 235)))
        if "center_offset_cm_projected" in measurements:
            lines.append((f"Table-plane projection: {measurements['center_offset_cm_projected']:+.1f} cm (parallax applies)", (235, 235, 235)))
    if assessment.arm_assessment is not None:
        arms = assessment.arm_assessment
        policy = "REQUIRED" if arms["policy_enabled"] else "OBSERVATION ONLY"
        lines.append((f"Arms: {arms['posture']} | Left: {arms['left']} | Right: {arms['right']} | {policy}", (235, 235, 235)))
    lines.append((f"Processing: {processing_ms:.1f} ms | {'SYNTHETIC LANDMARKS - NOT MODEL INFERENCE' if synthetic else 'YOLO pose | BED ONLY'}", (235, 235, 235)))
    left, top = np.floor(table.corners.min(axis=0)).astype(int)
    right, bottom = np.ceil(table.corners.max(axis=0)).astype(int) + 1
    image = image[max(0, top):min(image.shape[0], bottom), max(0, left):min(image.shape[1], right)]
    panel = np.full((PANEL_HEIGHT, max(720, image.shape[1]), 3), 25, np.uint8)
    for index, (text, color) in enumerate(lines):
        scale = min(0.55, (panel.shape[1] - 24) / max(1, cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1, 1)[0][0]))
        cv2.putText(panel, text, (12, 26 + 30 * index), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
    canvas = np.zeros((image.shape[0], panel.shape[1], 3), np.uint8)
    canvas[:, :image.shape[1]] = image
    return np.vstack([panel, canvas])
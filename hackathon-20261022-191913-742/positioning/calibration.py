import cv2
import numpy as np


class TableCalibration:
    def __init__(
        self,
        corners_normalized: list[list[float]],
        frame_shape: tuple[int, ...],
        confirmed: bool = False,
        near_nadir: bool = False,
        dimensions_cm: tuple[float, float] | None = None,
    ):
        height, width = frame_shape[:2]
        self.frame_size = (width, height)
        corners = np.asarray(corners_normalized, dtype=np.float32)
        if min(height, width) < 2:
            raise ValueError("Frame dimensions must be at least 2 pixels")
        if corners.shape != (4, 2) or not np.isfinite(corners).all():
            raise ValueError("Table needs four finite corners: TL, TR, BR, BL")
        if np.any(corners < 0) or np.any(corners > 1):
            raise ValueError("Normalized table corners must be within [0, 1]")
        self.corners = corners * np.array([width - 1, height - 1], np.float32)
        if not cv2.isContourConvex(self.corners) or cv2.contourArea(self.corners) < 25:
            raise ValueError("Table corners must form a nondegenerate convex quadrilateral")
        self.confirmed = confirmed
        self.metric = dimensions_cm is not None
        self.quality_reason = None
        if dimensions_cm is not None:
            table_width, table_length = dimensions_cm
            if not np.isfinite(dimensions_cm).all() or min(dimensions_cm) <= 0:
                raise ValueError("Physical table dimensions must be positive and finite")
            target = np.array(
                [[-table_width / 2, 0], [table_width / 2, 0],
                 [table_width / 2, table_length], [-table_width / 2, table_length]],
                dtype=np.float32,
            )
            self.matrix = cv2.getPerspectiveTransform(self.corners, target)
            self.width = float(table_width)
            self.length = float(table_length)
        else:
            top_axis = self.corners[1] - self.corners[0]
            left_axis = self.corners[3] - self.corners[0]
            self.width = float(np.linalg.norm(top_axis))
            self.length = float(np.linalg.norm(left_axis))
            if min(self.width, self.length) < 1:
                raise ValueError("Table edges must be nondegenerate")
            lateral = top_axis / self.width
            longitudinal = left_axis / self.length
            closure = np.linalg.norm(self.corners[2] - self.corners[1] - left_axis)
            rectangular = abs(float(lateral @ longitudinal)) < 0.02 and closure < 0.02 * min(self.width, self.length)
            if not near_nadir or not rectangular:
                self.quality_reason = "uncalibrated_perspective_or_unconfirmed_nadir"
            origin = (self.corners[0] + self.corners[1]) / 2
            self.matrix = np.array(
                [[*lateral, -float(lateral @ origin)],
                 [*longitudinal, -float(longitudinal @ origin)], [0, 0, 1]],
                dtype=np.float64,
            )
        if not confirmed:
            self.quality_reason = "table_setup_not_confirmed"

    def transform(self, points: np.ndarray) -> np.ndarray:
        return cv2.perspectiveTransform(
            np.asarray(points, np.float32).reshape(-1, 1, 2), self.matrix
        ).reshape(-1, 2)

    def to_image(self, points: np.ndarray) -> np.ndarray:
        return cv2.perspectiveTransform(
            np.asarray(points, np.float32).reshape(-1, 1, 2), np.linalg.inv(self.matrix)
        ).reshape(-1, 2)

    def contains(self, points: np.ndarray) -> bool:
        return all(cv2.pointPolygonTest(self.corners, tuple(map(float, point)), False) >= 0 for point in points)

    def intersects_box(self, box: np.ndarray) -> bool:
        left, top, right, bottom = map(float, box)
        if right <= left or bottom <= top:
            return False
        polygon = np.array([[left, top], [right, top], [right, bottom], [left, bottom]], np.float32)
        area, _ = cv2.intersectConvexConvex(self.corners, polygon)
        return area > 0
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from positioning.types import PoseDetection


class PerceptionBackend(Protocol):
    def detect(self, frame: np.ndarray) -> list[PoseDetection]: ...


class BedView:
    def __init__(self, frame: np.ndarray, corners_normalized: list[list[float]]):
        height, width = frame.shape[:2]
        self.corners = np.asarray(corners_normalized, np.float32) * [width - 1, height - 1]
        self.corners = self.corners.astype(np.float32)
        view_width = int(round((np.linalg.norm(self.corners[1] - self.corners[0]) + np.linalg.norm(self.corners[2] - self.corners[3])) / 2))
        view_height = int(round((np.linalg.norm(self.corners[3] - self.corners[0]) + np.linalg.norm(self.corners[2] - self.corners[1])) / 2))
        if min(view_width, view_height) < 2:
            raise ValueError("Bed crop must be at least two pixels wide and long")
        padding = max(8, int(min(view_width, view_height) * 0.1))
        target = np.array([[padding, padding], [padding + view_width - 1, padding],
                           [padding + view_width - 1, padding + view_height - 1],
                           [padding, padding + view_height - 1]], np.float32)
        self.matrix = cv2.getPerspectiveTransform(self.corners, target)
        self.inverse = np.linalg.inv(self.matrix)
        mask = np.zeros(frame.shape[:2], np.uint8)
        cv2.fillConvexPoly(mask, self.corners.astype(np.int32), 255)
        masked = cv2.bitwise_and(frame, frame, mask=mask)
        self.image = cv2.warpPerspective(masked, self.matrix, (view_width + 2 * padding, view_height + 2 * padding))

    def restore(self, detection: PoseDetection) -> PoseDetection:
        left, top, right, bottom = detection.box
        box_corners = np.array([[left, top], [right, top], [right, bottom], [left, bottom]], np.float32)
        original = cv2.perspectiveTransform(box_corners.reshape(-1, 1, 2), self.inverse).reshape(-1, 2)
        box = np.concatenate([original.min(axis=0), original.max(axis=0)])
        keypoints = detection.keypoints.copy()
        if keypoints.shape == (17, 3):
            finite = np.isfinite(keypoints[:, :2]).all(axis=1)
            if np.any(finite):
                keypoints[finite, :2] = cv2.perspectiveTransform(
                    keypoints[finite, :2].astype(np.float32).reshape(-1, 1, 2), self.inverse
                ).reshape(-1, 2)
            for index in np.flatnonzero(finite):
                if cv2.pointPolygonTest(self.corners, tuple(map(float, keypoints[index, :2])), False) < 0:
                    keypoints[index, 2] = 0.0
        return PoseDetection(box, detection.confidence, keypoints)


class YoloPoseBackend:
    def __init__(self, model_config: dict, config_directory: Path, bed_corners: list[list[float]] | None = None):
        from ultralytics import YOLO

        self.config = model_config
        self.bed_corners = bed_corners
        cpu_threads = model_config.get("cpu_threads")
        if cpu_threads is not None:
            import torch

            torch.set_num_threads(cpu_threads)
        weights = Path(model_config["weights"])
        if not weights.is_absolute():
            weights = config_directory / weights
        if not weights.is_file():
            raise FileNotFoundError(
                f"Pose weights not found: {weights}. Download the configured pretrained "
                "weights once (see README); inference then runs offline. Use --demo without weights."
            )
        self.model = YOLO(str(weights), task="pose")

    def detect(self, frame: np.ndarray) -> list[PoseDetection]:
        view = BedView(frame, self.bed_corners) if self.bed_corners is not None else None
        result = self.model.predict(
            view.image if view is not None else frame,
            imgsz=self.config["image_size"],
            conf=self.config["confidence"],
            device=self.config["device"],
            classes=[0],
            verbose=False,
        )[0]
        if result.boxes is None:
            return []
        boxes = result.boxes.xyxy.cpu().numpy()
        confidences = result.boxes.conf.cpu().numpy()
        keypoints = None if result.keypoints is None else result.keypoints.data.cpu().numpy()
        detections = [
            PoseDetection(box, float(confidence), keypoints[index] if keypoints is not None and index < len(keypoints) else np.empty((0, 3)))
            for index, (box, confidence) in enumerate(zip(boxes, confidences))
        ]
        return [view.restore(detection) for detection in detections] if view is not None else detections
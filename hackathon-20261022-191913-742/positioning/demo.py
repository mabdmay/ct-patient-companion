import cv2
import numpy as np

from positioning.camera import Frame, utc_now
from positioning.types import PoseDetection


DEMO_CORNERS = [[0.2, 0.05], [0.8, 0.05], [0.8, 0.95], [0.2, 0.95]]
SCENES = ["centered", "shifted", "rotated", "occluded", "empty", "ambiguous"]


def synthetic_frames():
    for index in range(120):
        scene = SCENES[index // 20]
        image = np.full((720, 960, 3), (65, 65, 65), np.uint8)
        cv2.rectangle(image, (192, 36), (767, 683), (185, 185, 185), -1)
        keypoints = np.zeros((17, 3), dtype=float)
        center = np.array([479.5 + (90 if scene == "shifted" else 0), 360])
        angle = np.radians(18 if scene == "rotated" else 0)
        axis = np.array([np.sin(angle), np.cos(angle)])
        side = np.array([axis[1], -axis[0]])
        for indices, location in [([5, 6], -100), ([11, 12], 100), ([13, 14], 190), ([15, 16], 275)]:
            for keypoint_index, sign in zip(indices, [-1, 1]):
                keypoints[keypoint_index] = [*(center + axis * location + side * sign * 55), 0.95]
        for keypoint_index, parent, displacement in [(7, 5, 80), (8, 6, 80), (9, 5, 155), (10, 6, 155)]:
            keypoints[keypoint_index] = [*(keypoints[parent, :2] + axis * displacement + side * (-25 if keypoint_index % 2 else 25)), 0.95]
        keypoints[0] = [*(center - axis * 175), 0.95]
        detections = []
        if scene != "empty":
            polygon = keypoints[[5, 6, 12, 11], :2].astype(np.int32)
            cv2.fillConvexPoly(image, polygon, (130, 170, 115))
            cv2.circle(image, tuple(keypoints[0, :2].astype(int)), 35, (180, 200, 200), -1)
            for start, end in [(11, 13), (13, 15), (12, 14), (14, 16), (5, 7), (7, 9), (6, 8), (8, 10)]:
                cv2.line(image, tuple(keypoints[start, :2].astype(int)), tuple(keypoints[end, :2].astype(int)), (130, 170, 115), 20)
            if scene == "occluded":
                cv2.rectangle(image, (300, 240), (680, 380), (105, 105, 105), -1)
                keypoints[[5, 6], 2] = 0.1
            detections = [PoseDetection(np.array([250, 100, 750, 680]), 0.98, keypoints)]
            if scene == "ambiguous":
                extra = keypoints.copy()
                extra[:, 0] += 100
                detections.append(PoseDetection(np.array([350, 100, 850, 680]), 0.95, extra))
        cv2.putText(image, f"Synthetic case: {scene}", (12, 705), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1)
        yield Frame(image, index, utc_now(), index / 10), detections
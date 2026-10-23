import unittest

import cv2
import numpy as np

from positioning.perception import BedView
from positioning.types import PoseDetection


class BedViewTests(unittest.TestCase):
    def setUp(self):
        self.corners = [[0.2, 0.8], [0.2, 0.2], [0.8, 0.2], [0.8, 0.8]]

    def test_pixels_outside_bed_never_reach_model(self):
        image = np.full((101, 201, 3), 255, np.uint8)
        image[20:81, 40:161] = 0
        view = BedView(image, self.corners)
        self.assertEqual(int(view.image.max()), 0)
        self.assertGreater(view.image.shape[0], view.image.shape[1])

    def test_round_trip_landmarks_and_box(self):
        view = BedView(np.zeros((101, 201, 3), np.uint8), self.corners)
        original = np.array([[80, 40], [80, 60], [120, 40], [120, 60]], np.float32)
        warped = cv2.perspectiveTransform(original.reshape(-1, 1, 2), view.matrix).reshape(-1, 2)
        keypoints = np.zeros((17, 3), float)
        keypoints[[5, 6, 11, 12], :2] = warped
        keypoints[[5, 6, 11, 12], 2] = 0.9
        detection = PoseDetection(np.concatenate([warped.min(axis=0), warped.max(axis=0)]), 0.95, keypoints)
        restored = view.restore(detection)
        np.testing.assert_allclose(restored.keypoints[[5, 6, 11, 12], :2], original, atol=1e-4)
        np.testing.assert_allclose(restored.box, [80, 40, 120, 60], atol=1e-4)

    def test_landmarks_in_black_padding_are_not_visible(self):
        view = BedView(np.zeros((101, 201, 3), np.uint8), self.corners)
        keypoints = np.ones((17, 3), float)
        result = view.restore(PoseDetection(np.array([0, 0, 10, 10]), 0.9, keypoints))
        self.assertTrue(np.all(result.keypoints[:, 2] == 0))

    def test_all_nonfinite_landmarks_do_not_crash_mapping(self):
        view = BedView(np.zeros((101, 201, 3), np.uint8), self.corners)
        points = np.full((17, 3), np.nan)
        result = view.restore(PoseDetection(np.array([0, 0, 10, 10]), 0.9, points))
        self.assertFalse(np.isfinite(result.keypoints).any())


if __name__ == "__main__":
    unittest.main()
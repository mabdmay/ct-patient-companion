import unittest
from dataclasses import replace

import numpy as np

from positioning.arms import ArmRules, assess_arms
from positioning.types import Status


def arm_pose(posture="OVER_TORSO"):
    points = np.zeros((17, 3), dtype=float)
    points[[5, 6, 11, 12]] = [[-50, 0, 0.95], [50, 0, 0.95], [-40, 200, 0.95], [40, 200, 0.95]]
    if posture == "OVER_TORSO":
        arms = [[-80, 90], [80, 90], [20, 65], [-20, 65]]
    elif posture == "ARMS_RAISED":
        arms = [[-80, -90], [80, -90], [-40, -170], [40, -170]]
    else:
        arms = [[-65, 100], [65, 100], [-55, 190], [55, 190]]
    points[[7, 8, 9, 10], :2] = arms
    points[[7, 8, 9, 10], 2] = 0.95
    return points


class ArmTests(unittest.TestCase):
    def test_recognizes_each_posture_and_policy(self):
        for posture in ["OVER_TORSO", "ARMS_RAISED", "ALONGSIDE_BODY"]:
            with self.subTest(posture=posture):
                result = assess_arms(arm_pose(posture), ArmRules(allowed_postures=(posture,)))
                self.assertEqual(result.posture, posture)
                self.assertEqual(result.status, Status.WITHIN_CRITERIA)

    def test_over_torso_rejected_by_raised_protocol(self):
        result = assess_arms(arm_pose(), ArmRules(allowed_postures=("ARMS_RAISED",)))
        self.assertEqual(result.status, Status.REPOSITION_REQUIRED)
        self.assertIn("arm_posture_not_allowed", result.reasons)

    def test_folded_hands_near_shoulder_span_edge(self):
        points = arm_pose()
        points[[9, 10], 0] = [-40, 40]
        self.assertEqual(assess_arms(points, ArmRules()).posture, "OVER_TORSO")

    def test_downward_forearms_near_waist_are_not_chest_folded(self):
        points = arm_pose("ALONGSIDE_BODY")
        points[[7, 8], 0] = [-50, 50]
        points[[9, 10], 0] = [-40, 40]
        self.assertEqual(assess_arms(points, ArmRules()).posture, "ALONGSIDE_BODY")

    def test_optional_policy_does_not_fail_torso_only_protocol(self):
        result = assess_arms(np.zeros((17, 3)), ArmRules())
        self.assertIsNone(result.status)
        self.assertEqual(result.posture, "UNCERTAIN")

    def test_missing_or_occluded_wrist_is_uncertain(self):
        for confidence in [0.0, 0.49, np.nan, np.inf]:
            points = arm_pose()
            points[9, 2] = confidence
            self.assertEqual(assess_arms(points, ArmRules(allowed_postures=("OVER_TORSO",))).status, Status.UNCERTAIN)

    def test_rotation_scale_and_translation_invariance(self):
        points = arm_pose()
        for angle in [0, 45, 90, 180, 270]:
            radians = np.radians(angle)
            rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
            rotated = points.copy()
            rotated[:, :2] = points[:, :2] @ rotation.T * 2.5 + [800, 500]
            self.assertEqual(assess_arms(rotated, ArmRules()).posture, "OVER_TORSO")

    def test_mixed_recognized_arms(self):
        points = arm_pose("ARMS_RAISED")
        points[[8, 10]] = arm_pose("ALONGSIDE_BODY")[[8, 10]]
        result = assess_arms(points, ArmRules(allowed_postures=("ARMS_RAISED",)))
        self.assertEqual(result.posture, "MIXED")
        self.assertEqual(result.status, Status.REPOSITION_REQUIRED)

    def test_unclassified_and_implausible_geometry(self):
        points = arm_pose()
        points[9, :2] = [-800, 900]
        self.assertEqual(assess_arms(points, ArmRules()).posture, "UNCERTAIN")
        points = arm_pose()
        points[9, :2] = points[7, :2]
        self.assertEqual(assess_arms(points, ArmRules()).posture, "UNCERTAIN")

    def test_margins_are_configurable(self):
        rules = replace(ArmRules(), raised_wrist_margin=1.0)
        self.assertEqual(assess_arms(arm_pose("ARMS_RAISED"), rules).posture, "UNCERTAIN")


if __name__ == "__main__":
    unittest.main()
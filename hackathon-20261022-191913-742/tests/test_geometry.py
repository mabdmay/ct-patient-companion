import unittest
from dataclasses import replace

import numpy as np

from positioning.calibration import TableCalibration
from positioning.geometry import assess_position
from positioning.types import PoseDetection, Rules, Status


def make_patient(offset=0.0, angle=0.0):
    keypoints = np.zeros((17, 3), dtype=float)
    axis = np.array([np.sin(np.radians(angle)), np.cos(np.radians(angle))]) * 100
    center = np.array([500 + offset * 600, 500])
    for indices, midpoint in [([5, 6], center - axis), ([11, 12], center + axis)]:
        keypoints[indices[0]] = [*(midpoint + [-50, 0]), 0.9]
        keypoints[indices[1]] = [*(midpoint + [50, 0]), 0.9]
    return PoseDetection(np.array([250, 200, 750, 800]), 0.95, keypoints)


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.corners = [[0.2, 0.1], [0.8, 0.1], [0.8, 0.9], [0.2, 0.9]]
        self.table = TableCalibration(self.corners, (1001, 1001, 3), confirmed=True, near_nadir=True)
        self.rules = Rules()

    def assess(self, patient=None, rules=None):
        return assess_position([patient if patient is not None else make_patient()], self.table, rules or self.rules)

    def test_centered(self):
        result = self.assess()
        self.assertEqual(result.status, Status.WITHIN_CRITERIA)
        self.assertAlmostEqual(result.measurements["center_offset_fraction"], 0)
        self.assertAlmostEqual(result.measurements["axis_error_deg"], 0)
        self.assertNotIn("center_offset_cm_projected", result.measurements)

    def test_signed_lateral_offset(self):
        for offset in [-0.12, 0.12]:
            result = self.assess(make_patient(offset=offset))
            self.assertEqual(result.status, Status.REPOSITION_REQUIRED)
            self.assertAlmostEqual(result.measurements["center_offset_fraction"], offset, places=5)

    def test_rotated(self):
        result = self.assess(make_patient(angle=15))
        self.assertIn("axis_error", result.reasons)
        self.assertAlmostEqual(result.measurements["axis_error_deg"], 15, places=4)

    def test_threshold_is_inclusive(self):
        self.assertEqual(self.assess(make_patient(offset=0.08, angle=8)).status, Status.WITHIN_CRITERIA)

    def test_reference(self):
        result = self.assess(make_patient(offset=0.12), replace(self.rules, reference_x_fraction=0.12))
        self.assertEqual(result.status, Status.WITHIN_CRITERIA)
        result = self.assess(rules=replace(self.rules, reference_y_fraction=0.2))
        self.assertIn("longitudinal_offset", result.reasons)

    def test_no_patient_and_ambiguity(self):
        for detections in [[], [make_patient(), make_patient()]]:
            self.assertEqual(assess_position(detections, self.table, self.rules).status, Status.UNCERTAIN)

    def test_staff_outside_table_is_ignored(self):
        staff = make_patient()
        staff.box = np.array([0, 0, 100, 900])
        self.assertEqual(assess_position([make_patient(), staff], self.table, self.rules).status, Status.WITHIN_CRITERIA)

    def test_side_person_with_overlapping_box_is_ignored(self):
        staff = make_patient()
        staff.keypoints[:, 0] -= 420
        self.assertEqual(assess_position([make_patient(), staff], self.table, self.rules).status, Status.WITHIN_CRITERIA)

    def test_required_arm_landmarks_gate_overall_status(self):
        from positioning.arms import ArmRules

        result = self.assess(rules=replace(self.rules, arm_rules=ArmRules(allowed_postures=("ALONGSIDE_BODY",))))
        self.assertEqual(result.status, Status.UNCERTAIN)
        self.assertIn("low_or_invalid_arm_confidence", result.reasons)
        self.assertEqual(result.arm_assessment["posture"], "UNCERTAIN")

    def test_folded_arms_change_overall_decision_by_protocol(self):
        from positioning.arms import ArmRules

        patient = make_patient()
        patient.keypoints[[7, 8, 9, 10]] = [[420, 490, 0.9], [580, 490, 0.9], [520, 465, 0.9], [480, 465, 0.9]]
        allowed = replace(self.rules, arm_rules=ArmRules(allowed_postures=("OVER_TORSO",)))
        rejected = replace(self.rules, arm_rules=ArmRules(allowed_postures=("ALONGSIDE_BODY",)))
        self.assertEqual(self.assess(patient, allowed).status, Status.WITHIN_CRITERIA)
        result = self.assess(patient, rejected)
        self.assertEqual(result.status, Status.REPOSITION_REQUIRED)
        self.assertIn("arm_posture_not_allowed", result.reasons)
        self.assertEqual(result.arm_assessment["allowed_postures"], ["ALONGSIDE_BODY"])

    def test_missing_low_confidence_and_invalid_landmarks(self):
        for value in [0, 0.49, np.nan, np.inf]:
            patient = make_patient()
            patient.keypoints[5, 2] = value
            self.assertEqual(self.assess(patient).status, Status.UNCERTAIN)
        patient = make_patient()
        patient.keypoints = np.zeros((0, 3))
        self.assertEqual(self.assess(patient).status, Status.UNCERTAIN)

    def test_outside_and_degenerate_torso(self):
        patient = make_patient()
        patient.keypoints[5, 0] = 0
        self.assertEqual(self.assess(patient).status, Status.UNCERTAIN)
        patient = make_patient()
        patient.keypoints[[11, 12]] = patient.keypoints[[5, 6]]
        self.assertEqual(self.assess(patient).status, Status.UNCERTAIN)

    def test_unconfirmed_setup(self):
        table = TableCalibration(self.corners, (1001, 1001, 3))
        self.assertEqual(assess_position([make_patient()], table, self.rules).status, Status.UNCERTAIN)

    def test_perspective_requires_dimensions(self):
        skew = [[0.3, 0.1], [0.7, 0.1], [0.8, 0.9], [0.2, 0.9]]
        table = TableCalibration(skew, (1001, 1001, 3), confirmed=True, near_nadir=True)
        self.assertIsNotNone(table.quality_reason)
        table = TableCalibration(skew, (1001, 1001, 3), confirmed=True, dimensions_cm=(60, 200))
        np.testing.assert_allclose(table.transform(table.corners), [[-30, 0], [30, 0], [30, 200], [-30, 200]], atol=1e-4)

    def test_metric_projection(self):
        table = TableCalibration(self.corners, (1001, 1001, 3), confirmed=True, dimensions_cm=(60, 80))
        result = assess_position([make_patient(offset=0.1)], table, self.rules)
        self.assertAlmostEqual(result.measurements["center_offset_cm_projected"], 6, places=4)

    def test_invalid_calibration(self):
        for corners in [self.corners[:3], [[0, 0]] * 4, [[-1, 0], [1, 0], [1, 1], [0, 1]]]:
            with self.assertRaises(ValueError):
                TableCalibration(corners, (1001, 1001, 3))


if __name__ == "__main__":
    unittest.main()
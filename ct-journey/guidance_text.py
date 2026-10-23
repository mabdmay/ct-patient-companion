"""Posture-assessment reason codes -> short, patient-facing spoken/display guidance.

The reason vocabulary comes from the positioning repo (positioning/geometry.py,
positioning/arms.py, positioning/calibration.py) and is not translated to patient-facing
text there - that repo only emits machine-readable advisory reasons. This mapping is kept
in this orchestrator rather than edited into that repo, so it stays untouched/reusable.
"""

POSITIVE = "You're in the right position. Please stay still."

REASON_TEXT = {
    "configured_2d_checks_passed": POSITIVE,
    "arm_posture_allowed": POSITIVE,
    "arm_posture_observed": POSITIVE,
    "no_patient_on_table": "I can't see you on the bed yet. Please lie down in the marked area.",
    "ambiguous_multiple_people": "I'm seeing more than one person near the bed. Could anyone else please step back?",
    "lateral_offset": "Please shift a little toward the center of the bed.",
    "axis_error": "Please straighten up along the centerline of the bed.",
    "longitudinal_offset": "Please slide slightly up or down to center yourself on the bed.",
    "arm_posture_not_allowed": "Please rest your arms alongside your body.",
    "invalid_detection": "I'm having trouble getting a clear view. Please hold still for a moment.",
    "missing_pose_landmarks": "I can't see your whole body clearly. Please make sure you're fully in view.",
    "low_or_invalid_landmark_confidence": "I can't see your position clearly enough. Please hold still.",
    "torso_landmarks_outside_table": "Please move fully onto the bed.",
    "degenerate_torso_geometry": "I can't quite make out your position. Please lie flat and hold still.",
    "missing_arm_landmarks": "I can't see both of your arms. Please keep them visible.",
    "low_or_invalid_arm_confidence": "I can't see your arms clearly. Please keep them visible and still.",
    "degenerate_arm_reference_geometry": "I can't see your arms clearly. Please keep them visible and still.",
    "insufficient_projected_shoulder_width": "Please face up so I can see your shoulders clearly.",
    "implausible_projected_arm_geometry": "I can't tell how your arms are positioned. Please keep them visible.",
    "arm_geometry_unclassified": "I can't quite tell your arm position. Please keep both arms visible.",
    "table_setup_not_confirmed": "One moment, checking the camera setup.",
    "uncalibrated_perspective_or_unconfirmed_nadir": "One moment, checking the camera setup.",
}

FALLBACK_TEXT = "Hold still for a moment while I check your position."


def guidance_for(reasons: list[str]) -> str:
    """Pick the single most relevant patient-facing sentence for this assessment.

    Prefers the first *actionable* (non-positive) reason, so a reposition instruction
    is never drowned out by an incidental "arm_posture_observed" earlier in the list.
    """
    if not reasons:
        return FALLBACK_TEXT
    for reason in reasons:
        text = REASON_TEXT.get(reason)
        if text and text != POSITIVE:
            return text
    return REASON_TEXT.get(reasons[0], FALLBACK_TEXT)

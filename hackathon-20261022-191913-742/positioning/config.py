from pathlib import Path
from dataclasses import fields

import numpy as np
import yaml

from positioning.arms import ArmRules, POSTURES
from positioning.calibration import TableCalibration
from positioning.types import Rules


def load_config(path: Path) -> tuple[dict, Rules]:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    try:
        model = config["model"]
        table = config["table"]
        reference = config["reference"]
        thresholds = config["thresholds"]
        for key in ["camera_id", "reference_id"]:
            if not isinstance(config[key], str) or not config[key].strip():
                raise ValueError(f"{key} must be a nonempty string")
        for key in ["confirmed", "near_nadir"]:
            if not isinstance(table[key], bool):
                raise ValueError(f"table.{key} must be a YAML boolean")
        if not isinstance(model["weights"], str) or not model["weights"].endswith("-pose.pt"):
            raise ValueError("model.weights must name a YOLO -pose.pt model")
        if not isinstance(model["device"], str):
            raise ValueError("model.device must be a string such as cpu or '0'")
        if type(model["image_size"]) is not int or model["image_size"] < 32:
            raise ValueError("model.image_size must be an integer of at least 32")
        cpu_threads = model.get("cpu_threads")
        if cpu_threads is not None and (type(cpu_threads) is not int or not 1 <= cpu_threads <= 64):
            raise ValueError("model.cpu_threads must be null or an integer in [1, 64]")
        arm_config = dict(config.get("arms", {}))
        allowed = arm_config.get("allowed_postures")
        if allowed is not None:
            if not isinstance(allowed, list) or not allowed or any(not isinstance(label, str) or label not in POSTURES for label in allowed):
                raise ValueError(f"arms.allowed_postures must be null or a nonempty list from {sorted(POSTURES)}")
            arm_config["allowed_postures"] = tuple(allowed)
        arm_rules = ArmRules(**arm_config)
        for item in fields(arm_rules):
            if item.name == "allowed_postures":
                continue
            value = getattr(arm_rules, item.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 <= value <= 2:
                raise ValueError(f"arms.{item.name} must be finite and in [0, 2]")
        if not 0 < arm_rules.min_confidence <= 1 or arm_rules.max_segment_length <= 0:
            raise ValueError("Arm confidence must be in (0, 1] and maximum segment length must be positive")
        rules = Rules(
            min_detection_confidence=float(model["confidence"]),
            min_keypoint_confidence=float(thresholds["keypoint_confidence"]),
            min_torso_length_fraction=float(thresholds["min_torso_length_fraction"]),
            reference_x_fraction=float(reference["lateral_fraction"]),
            reference_y_fraction=None if reference["longitudinal_fraction"] is None else float(reference["longitudinal_fraction"]),
            reference_axis_deg=float(reference["axis_deg"]),
            max_lateral_fraction=float(thresholds["max_lateral_fraction"]),
            max_angle_deg=float(thresholds["max_angle_deg"]),
            max_longitudinal_fraction=float(thresholds["max_longitudinal_fraction"]),
            arm_rules=arm_rules,
        )
        numeric_values = [value for key, value in vars(rules).items() if value is not None and key != "arm_rules"]
        if not np.isfinite(numeric_values).all():
            raise ValueError("All reference values and thresholds must be finite")
        if not 0 < rules.min_detection_confidence <= 1 or not 0 < rules.min_keypoint_confidence <= 1:
            raise ValueError("Detection and keypoint confidence must be in (0, 1]")
        if rules.min_torso_length_fraction <= 0:
            raise ValueError("Minimum torso length must be positive")
        if not 0 <= rules.max_lateral_fraction <= 1 or not 0 <= rules.max_longitudinal_fraction <= 1:
            raise ValueError("Fraction tolerances must be in [0, 1]")
        if not 0 <= rules.max_angle_deg <= 90:
            raise ValueError("Angular tolerance must be in [0, 90]")
        if not -0.5 <= rules.reference_x_fraction <= 0.5:
            raise ValueError("Reference lateral fraction must be in [-0.5, 0.5]")
        if rules.reference_y_fraction is not None and not 0 <= rules.reference_y_fraction <= 1:
            raise ValueError("Reference longitudinal fraction must be in [0, 1]")
        dimensions = table.get("dimensions_cm")
        if dimensions is not None and (not isinstance(dimensions, list) or len(dimensions) != 2):
            raise ValueError("table.dimensions_cm must be null or [width, length]")
        TableCalibration(table["corners_normalized"], (1001, 1001, 3), table["confirmed"], table["near_nadir"], dimensions)
    except (KeyError, TypeError) as error:
        raise ValueError(f"Invalid or missing configuration field: {error}") from error
    return config, rules


def build_table(config: dict, frame_shape: tuple[int, ...]) -> TableCalibration:
    table = config["table"]
    return TableCalibration(
        table["corners_normalized"], frame_shape,
        table["confirmed"], table["near_nadir"], table.get("dimensions_cm"),
    )
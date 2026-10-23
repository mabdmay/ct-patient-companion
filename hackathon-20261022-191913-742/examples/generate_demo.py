import argparse
import copy
import json
from pathlib import Path

import cv2
import yaml

from positioning.camera import FrameOutput
from positioning.config import build_table, load_config
from positioning.demo import DEMO_CORNERS, SCENES, synthetic_frames
from positioning.geometry import assess_position
from positioning.integration import make_event
from positioning.visualization import annotate


def main():
    parser = argparse.ArgumentParser(description="Generate nonidentifying synthetic input and annotated fixtures")
    parser.add_argument("--directory", type=Path, default=Path("examples/generated"))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    config, rules = load_config(root / "config.yaml")
    config = copy.deepcopy(config)
    config["camera_id"] = "synthetic_camera"
    config["reference_id"] = "synthetic_centerline_v1"
    config["table"] = {"corners_normalized": DEMO_CORNERS, "confirmed": True, "near_nadir": True, "dimensions_cm": None}
    config["model"]["weights"] = str((root / config["model"]["weights"]).resolve())
    with (args.directory / "synthetic_config.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
    video = FrameOutput(args.directory / "synthetic_input.avi", 10.0)
    try:
        with (args.directory / "expected_events.jsonl").open("w", encoding="utf-8") as events:
            for frame, detections in synthetic_frames():
                video.write(frame.image)
                table = build_table(config, frame.image.shape)
                result = assess_position(detections, table, rules)
                event = make_event(result, config, frame.timestamp_utc, frame.index, frame.source_time_seconds, 0, 0, True)
                events.write(json.dumps(event, allow_nan=False) + "\n")
                if frame.index % 20 == 0:
                    scene = SCENES[frame.index // 20]
                    rendered = annotate(frame.image, detections, table, rules, result, 0, True)
                    if not cv2.imwrite(str(args.directory / f"{scene}.png"), frame.image):
                        raise OSError("Cannot save synthetic source image")
                    if not cv2.imwrite(str(args.directory / f"{scene}_annotated.png"), rendered):
                        raise OSError("Cannot save annotated synthetic image")
    finally:
        video.close()
    print(f"Generated fixtures in {args.directory.resolve()}")
    print("Injected-landmark expectations are NOT YOLO accuracy measurements.")


if __name__ == "__main__":
    main()
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from positioning.types import Status
from positioning.visualization import COLORS, PANEL_HEIGHT


def summarize(events_path: Path, annotations: Path, prefix: Path) -> dict:
    with events_path.open(encoding="utf-8") as handle:
        events = [json.loads(line) for line in handle if line.strip()]
    if not events:
        raise ValueError("No events to summarize")
    summary = {
        "frames": len(events),
        "status_counts": dict(Counter(event["status"] for event in events)),
        "arm_posture_counts": dict(Counter((event.get("arm_assessment") or {}).get("posture", "NOT_ASSESSED") for event in events)),
        "reason_counts": dict(Counter(reason for event in events for reason in event["reasons"])),
        "inference_p50_ms": float(np.percentile([event["inference_ms"] for event in events], 50)),
        "inference_p95_ms": float(np.percentile([event["inference_ms"] for event in events], 95)),
        "processing_p50_ms": float(np.percentile([event["processing_ms"] for event in events], 50)),
        "processing_p95_ms": float(np.percentile([event["processing_ms"] for event in events], 95)),
        "advisory_only": True,
        "accuracy_evaluated": False,
        "limitations": ["No independent ground-truth labels or held-out evaluation", "Arm rules tuned on this photo set", "No leg, depth, supine/prone or motion criterion", "Image-plane demo bed ROI, not metric calibration"],
    }
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(prefix) + "_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, allow_nan=False)
    columns = ["frame_index", "source_file", "status", "arm_posture", "left_arm", "right_arm", "reasons"]
    with Path(str(prefix) + ".csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for event in events:
            arms = event.get("arm_assessment") or {}
            writer.writerow({"frame_index": event["frame_index"], "source_file": event.get("source_file"),
                             "status": event["status"], "arm_posture": arms.get("posture", "NOT_ASSESSED"),
                             "left_arm": arms.get("left"), "right_arm": arms.get("right"),
                             "reasons": ";".join(event["reasons"])})
    columns_count, tile_width, tile_height = 3, 600, 260
    rows = (len(events) + columns_count - 1) // columns_count
    sheet = np.full((rows * tile_height, columns_count * tile_width, 3), 25, np.uint8)
    for index, event in enumerate(events):
        annotated = cv2.imread(str(annotations / f"{event['frame_index']:04d}.png"))
        if annotated is None:
            raise OSError(f"Missing annotation for frame {event['frame_index']}")
        bed = annotated[PANEL_HEIGHT:]
        scale = min((tile_width - 12) / bed.shape[1], 165 / bed.shape[0])
        resized = cv2.resize(bed, (max(1, round(bed.shape[1] * scale)), max(1, round(bed.shape[0] * scale))))
        top = (index // columns_count) * tile_height
        left = (index % columns_count) * tile_width
        color = COLORS[Status(event["status"])]
        arms = event.get("arm_assessment") or {}
        labels = [f"{event['frame_index']:02d}  {event.get('source_file', '')}",
                  event["status"] + " | " + arms.get("posture", "NOT_ASSESSED") + " | ADVISORY"]
        for label_index, label in enumerate(labels):
            cv2.putText(sheet, label, (left + 8, top + 20 + label_index * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.43, color, 1, cv2.LINE_AA)
        sheet[top + 55:top + 55 + resized.shape[0], left + 6:left + 6 + resized.shape[1]] = resized
        reason = ", ".join(event["reasons"])
        scale = min(0.4, (tile_width - 16) / max(1, cv2.getTextSize(reason, cv2.FONT_HERSHEY_SIMPLEX, 1, 1)[0][0]))
        cv2.putText(sheet, reason, (left + 8, top + tile_height - 15), cv2.FONT_HERSHEY_SIMPLEX, scale, (220, 220, 220), 1, cv2.LINE_AA)
    if not cv2.imwrite(str(prefix) + "_contact_sheet.jpg", sheet):
        raise OSError("Cannot save contact sheet")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Summarize bed-only photo results; does not calculate accuracy")
    parser.add_argument("--events", type=Path, default=Path("outputs/data_review.jsonl"))
    parser.add_argument("--annotations", type=Path, default=Path("outputs/data_review"))
    parser.add_argument("--prefix", type=Path, default=Path("outputs/data_review"))
    args = parser.parse_args()
    print(json.dumps(summarize(args.events, args.annotations, args.prefix), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
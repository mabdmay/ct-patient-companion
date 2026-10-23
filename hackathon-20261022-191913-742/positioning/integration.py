import json
from pathlib import Path

from positioning.types import Assessment


def make_event(
    assessment: Assessment, config: dict, timestamp_utc: str,
    frame_index: int, source_time_seconds: float | None, inference_ms: float,
    processing_ms: float, synthetic: bool,
) -> dict:
    return {
        "schema_version": "0.2",
        "timestamp_utc": timestamp_utc,
        "camera_id": config["camera_id"],
        "reference_id": config["reference_id"],
        "frame_index": frame_index,
        "source_time_seconds": source_time_seconds,
        "status": assessment.status.value,
        "reasons": assessment.reasons,
        "measurements": assessment.measurements,
        "arm_assessment": assessment.arm_assessment,
        "perception_confidence": assessment.perception_confidence,
        "inference_ms": round(inference_ms, 3),
        "processing_ms": round(processing_ms, 3),
        "assessment_scope": "single_frame_2d_geometry",
        "synthetic_landmarks": synthetic,
        "advisory_only": True,
    }


class JsonEventSink:
    def __init__(self, path: Path | None):
        self.handle = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = path.open("w", encoding="utf-8")

    def emit(self, event: dict):
        text = json.dumps(event, allow_nan=False, separators=(",", ":"))
        print(text, flush=True)
        if self.handle is not None:
            self.handle.write(text + "\n")
            self.handle.flush()

    def close(self):
        if self.handle is not None:
            self.handle.close()
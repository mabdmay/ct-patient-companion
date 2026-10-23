import argparse
import copy
import logging
from collections import deque
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from positioning.arms import ArmRules, POSTURES
from positioning.camera import CameraInput, FrameOutput, utc_now
from positioning.config import build_table, load_config
from positioning.demo import DEMO_CORNERS, synthetic_frames
from positioning.geometry import assess_position
from positioning.integration import JsonEventSink, make_event
from positioning.perception import YoloPoseBackend
from positioning.types import Assessment, Status
from positioning.visualization import annotate


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Advisory CT positioning: Phase 1, single-frame 2D geometry only")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / "config.yaml")
    parser.add_argument("--source", default="0", help="Image/video path, image directory, or numeric webcam index")
    parser.add_argument("--allowed-arms", nargs="+", choices=sorted(POSTURES), help="Require one of these arm postures for this protocol")
    parser.add_argument("--demo", action="store_true", help="Synthetic frames and injected landmarks; no model evaluation")
    parser.add_argument("--no-display", action="store_true", help="Run without OpenCV windows")
    parser.add_argument("--output", type=Path, help="Save annotated image, .mp4/.avi video, or numbered images in a directory")
    parser.add_argument("--jsonl", type=Path, help="Save per-frame advisory JSON events (also printed to stdout)")
    parser.add_argument("--max-frames", type=int, help="Stop after this number of processed frames")
    args = parser.parse_args(argv)
    if args.max_frames is not None and args.max_frames <= 0:
        parser.error("--max-frames must be positive")
    paths = [path.resolve() for path in [args.output, args.jsonl] if path is not None]
    protected = {args.config.resolve(), Path(args.source).resolve()}
    if len(paths) != len(set(paths)) or any(path in protected for path in paths):
        parser.error("Output paths must differ from each other, the config, and the input")
    if Path(args.source).is_dir() and any(Path(args.source).resolve() in path.parents for path in paths):
        parser.error("Store generated outputs outside the input image directory")
    return args


def run(args) -> int:
    config, rules = load_config(args.config)
    if args.allowed_arms:
        rules = replace(rules, arm_rules=replace(rules.arm_rules or ArmRules(), allowed_postures=tuple(args.allowed_arms)))
        config["reference_id"] += "_override_" + "_".join(args.allowed_arms).lower()
    if args.demo:
        config = copy.deepcopy(config)
        config["table"] = {"corners_normalized": DEMO_CORNERS, "confirmed": True, "near_nadir": True, "dimensions_cm": None}
        config["camera_id"] = "synthetic_camera"
        config["reference_id"] += "_synthetic_geometry"
        logging.warning("Synthetic demo injects landmarks; it does not evaluate YOLO")
    events = JsonEventSink(args.jsonl)
    source = None
    output = None
    latencies = deque(maxlen=1000)
    inference_times = deque(maxlen=1000)
    processed_frames = 0
    frame_index = -1
    try:
        backend = None if args.demo else YoloPoseBackend(config["model"], args.config.resolve().parent, config["table"]["corners_normalized"])
        if args.demo:
            frames = synthetic_frames()
            fps = 10.0
        else:
            source = CameraInput(args.source)
            frames = ((frame, None) for frame in source)
            fps = source.fps
        output = FrameOutput(args.output, fps)
        for frame, injected_detections in frames:
            frame_index = frame.index
            started = perf_counter()
            detections = injected_detections if args.demo else backend.detect(frame.image)
            inference_ms = (perf_counter() - started) * 1000 if not args.demo else 0.0
            table = build_table(config, frame.image.shape)
            assessment = assess_position(detections, table, rules)
            decision_ms = (perf_counter() - started) * 1000
            rendered = annotate(frame.image, detections, table, rules, assessment, decision_ms, args.demo)
            output.write(rendered)
            processing_ms = (perf_counter() - started) * 1000
            latencies.append(processing_ms)
            inference_times.append(inference_ms)
            processed_frames += 1
            event = make_event(assessment, config, frame.timestamp_utc, frame.index, frame.source_time_seconds, inference_ms, processing_ms, args.demo)
            event["source_file"] = frame.source_file
            events.emit(event)
            if not args.no_display:
                cv2.imshow("CT positioning advisory", rendered)
                delay = 0 if source is not None and source.still is not None else (100 if args.demo else 1)
                if cv2.waitKey(delay) & 0xFF in [ord("q"), 27]:
                    break
            if args.max_frames is not None and processed_frames >= args.max_frames:
                break
        return 0
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        logging.error("Processing stopped: %s", error)
        failure = Assessment(Status.UNCERTAIN, ["input_or_processing_failure"])
        events.emit(make_event(failure, config, utc_now(), frame_index + 1, None, 0.0, 0.0, args.demo))
        return 1
    finally:
        if source is not None:
            source.close()
        if output is not None:
            output.close()
        events.close()
        if not args.no_display:
            cv2.destroyAllWindows()
        if latencies:
            logging.info(
                "Processed %d frames | last %d processing p50/p95 %.1f/%.1f ms | inference p50/p95 %.1f/%.1f ms",
                processed_frames, len(latencies), *np.percentile(latencies, [50, 95]), *np.percentile(inference_times, [50, 95]),
            )


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError) as error:
        logging.error("Startup failed: %s", error)
        return 1
    except KeyboardInterrupt:
        logging.info("Stopped by operator")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
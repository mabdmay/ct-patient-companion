import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from positioning.camera import CameraInput
from positioning.config import build_table, load_config
from positioning.demo import SCENES, synthetic_frames
from positioning.geometry import assess_position
from positioning.integration import make_event
from positioning.types import Status
from positioning.visualization import annotate

from main import parse_args, run


ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def test_synthetic_scenes_and_json(self):
        config, rules = load_config(ROOT / "config.yaml")
        config["table"]["confirmed"] = True
        config["table"]["near_nadir"] = True
        expected = [Status.WITHIN_CRITERIA, Status.REPOSITION_REQUIRED, Status.REPOSITION_REQUIRED, Status.UNCERTAIN, Status.UNCERTAIN, Status.UNCERTAIN]
        rendered_shape = None
        for frame, detections in synthetic_frames():
            if frame.index % 20:
                continue
            with self.subTest(scene=SCENES[frame.index // 20]):
                table = build_table(config, frame.image.shape)
                result = assess_position(detections, table, rules)
                self.assertEqual(result.status, expected[frame.index // 20])
                rendered = annotate(frame.image, detections, table, rules, result, 0, True)
                if rendered_shape is None:
                    rendered_shape = rendered.shape
                self.assertEqual(rendered.shape, rendered_shape)
                bed_width = int(np.ceil(table.corners[:, 0].max()) - np.floor(table.corners[:, 0].min()) + 1)
                self.assertEqual(rendered.shape[1], max(720, bed_width))
                self.assertGreater(rendered.shape[0], 224)
                event = make_event(result, config, frame.timestamp_utc, frame.index, frame.source_time_seconds, 0, 0, True)
                self.assertTrue(json.loads(json.dumps(event, allow_nan=False))["advisory_only"])

    def test_image_and_video_input(self):
        with tempfile.TemporaryDirectory() as directory:
            image = np.zeros((128, 192, 3), np.uint8)
            image_path = Path(directory) / "test.png"
            self.assertTrue(cv2.imwrite(str(image_path), image))
            source = CameraInput(str(image_path))
            try:
                self.assertEqual(len(list(source)), 1)
            finally:
                source.close()
            video_path = Path(directory) / "test.avi"
            writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (192, 128))
            self.assertTrue(writer.isOpened())
            for _ in range(3):
                writer.write(image)
            writer.release()
            source = CameraInput(str(video_path))
            try:
                frames = list(source)
                self.assertEqual(len(frames), 3)
                self.assertAlmostEqual(frames[-1].source_time_seconds, 0.2)
            finally:
                source.close()

    def test_cli_synthetic_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "annotated.png"
            events = Path(directory) / "events.jsonl"
            result = subprocess.run(
                [sys.executable, str(ROOT / "main.py"), "--demo", "--no-display", "--max-frames", "1", "--output", str(output), "--jsonl", str(events)],
                capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNotNone(cv2.imread(str(output)))
            event = json.loads(events.read_text(encoding="utf-8"))
            self.assertEqual(event["status"], "WITHIN_CRITERIA")
            self.assertTrue(event["synthetic_landmarks"])

    def test_missing_input_fails(self):
        with self.assertRaises(OSError):
            CameraInput("missing_consent_video.avi")

    def test_folder_input_and_directory_output(self):
        from positioning.camera import FrameOutput

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_directory = root / "images"
            source_directory.mkdir()
            for name in ["b.png", "a.png"]:
                self.assertTrue(cv2.imwrite(str(source_directory / name), np.zeros((128, 192, 3), np.uint8)))
            source = CameraInput(str(source_directory))
            output = FrameOutput(root / "annotated", 10)
            try:
                frames = list(source)
                self.assertEqual([frame.source_file for frame in frames], ["a.png", "b.png"])
                for frame in frames:
                    output.write(frame.image)
            finally:
                source.close()
                output.close()
            self.assertEqual(len(list((root / "annotated").glob("*.png"))), 2)

    def test_startup_model_failure_is_uncertain_event(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "failure.jsonl"
            args = parse_args(["--no-display", "--jsonl", str(events)])
            with patch("main.YoloPoseBackend", side_effect=FileNotFoundError("missing model")):
                with redirect_stdout(StringIO()):
                    self.assertEqual(run(args), 1)
            event = json.loads(events.read_text(encoding="utf-8"))
            self.assertEqual(event["status"], "UNCERTAIN")
            self.assertEqual(event["measurements"], {})

    def test_protect_source_from_overwrite(self):
        with redirect_stdout(StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["--source", "input.png", "--output", "input.png"])


if __name__ == "__main__":
    unittest.main()
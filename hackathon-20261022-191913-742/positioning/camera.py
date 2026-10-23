from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass
class Frame:
    image: np.ndarray
    index: int
    timestamp_utc: str
    source_time_seconds: float | None = None
    source_file: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CameraInput:
    def __init__(self, source: str):
        self.capture = None
        self.still = None
        self.images = None
        self.source_name = Path(source).name
        self.is_camera = source.isdecimal() and not Path(source).is_file()
        self.fps = 10.0
        path = Path(source)
        if path.is_dir():
            self.images = sorted(item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES)
            if not self.images:
                raise OSError(f"No supported images in directory: {source}")
            return
        if not self.is_camera and not path.is_file():
            raise OSError(f"Input does not exist: {source}")
        if not self.is_camera and path.suffix.lower() in IMAGE_SUFFIXES:
            self.still = cv2.imread(str(path))
            if self.still is None:
                raise OSError(f"Cannot decode image: {path}")
        else:
            self.capture = cv2.VideoCapture(int(source) if self.is_camera else str(path))
            if not self.capture.isOpened():
                self.close()
                raise OSError(f"Cannot open {'camera' if self.is_camera else 'video'}: {source}")
            fps = self.capture.get(cv2.CAP_PROP_FPS)
            if np.isfinite(fps) and 0 < fps <= 240:
                self.fps = float(fps)

    def __iter__(self):
        if self.images is not None:
            for index, path in enumerate(self.images):
                image = cv2.imread(str(path))
                if image is None:
                    raise OSError(f"Cannot decode image: {path}")
                yield Frame(image, index, utc_now(), None, path.name)
            return
        if self.still is not None:
            yield Frame(self.still, 0, utc_now(), 0.0, self.source_name)
            return
        index = 0
        while True:
            success, image = self.capture.read()
            if not success:
                if self.is_camera or index == 0:
                    raise OSError("Camera read failed" if self.is_camera else "Video has no decodable frames")
                break
            source_time = None if self.is_camera else index / self.fps
            yield Frame(image, index, utc_now(), source_time, None if self.is_camera else self.source_name)
            index += 1

    def close(self):
        if self.capture is not None:
            self.capture.release()


class FrameOutput:
    def __init__(self, path: Path | None, fps: float):
        self.path = path
        self.fps = fps
        self.writer = None
        self.size = None
        self.index = 0
        self.directory = path is not None and not path.suffix
        if path is not None:
            if not self.directory and path.suffix.lower() not in IMAGE_SUFFIXES | {".mp4", ".avi"}:
                raise ValueError("Output must be a directory, image, .mp4, or .avi")
            (path if self.directory else path.parent).mkdir(parents=True, exist_ok=True)

    def write(self, image: np.ndarray):
        if self.path is None:
            return
        if self.directory:
            destination = self.path / f"{self.index:04d}.png"
            if not cv2.imwrite(str(destination), image):
                raise OSError(f"Cannot write image: {destination}")
            self.index += 1
            return
        if self.path.suffix.lower() in IMAGE_SUFFIXES:
            if not cv2.imwrite(str(self.path), image):
                raise OSError(f"Cannot write image: {self.path}")
            return
        height, width = image.shape[:2]
        if self.writer is None:
            codec = "MJPG" if self.path.suffix.lower() == ".avi" else "mp4v"
            self.writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*codec), self.fps, (width, height))
            self.size = (width, height)
            if not self.writer.isOpened():
                raise OSError(f"Cannot create video: {self.path}")
        if self.size != (width, height):
            raise ValueError("Input resolution changed; restart with new table calibration")
        self.writer.write(image)

    def close(self):
        if self.writer is not None:
            self.writer.release()
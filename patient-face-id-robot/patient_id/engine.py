"""Face detection + embedding (OpenCV YuNet + SFace). One shared instance, guarded by a lock."""
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class FaceObs:
    box: tuple          # (x, y, w, h) in the ORIGINAL image's pixels
    score: float        # detector confidence
    embedding: np.ndarray  # L2-normalised, shape (128,)


def decode_image(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not a decodable image")
    return img


def brighten(img: np.ndarray, target: float = 110.0) -> np.ndarray:
    """Adaptive gamma for dark frames; leaves normal frames untouched."""
    mean = float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean())
    if mean >= 70 or mean < 1:
        return img
    gamma = float(np.clip(np.log(target / 255) / np.log(mean / 255), 0.35, 1.0))
    lut = (np.linspace(0, 1, 256) ** gamma * 255).astype(np.uint8)
    return cv2.LUT(img, lut)


# YuNet is not roll-invariant: a head tilted ear-toward-shoulder loses detection confidence fast.
# These are only tried when the upright pass finds nothing, so the common frontal case pays no cost.
TILT_FALLBACK_DEG = (-25, 25, -45, 45)


def _rotated_detect(detector, work, angle):
    """Detect on `work` rotated by `angle` degrees; return (rows, image) with rows still in the
    rotated image's coordinates (alignCrop needs rows and image in the same frame)."""
    h, w = work.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(work, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    detector.setInputSize((w, h))
    _, rows = detector.detect(rotated)
    return rows, rotated


def _box_from_rotated(row, angle, frame_shape):
    """Map a detection box from a rotated frame back to the unrotated frame's coordinates
    (axis-aligned bounding box of the rotated corners; approximate, display/tracking only)."""
    h, w = frame_shape[:2]
    cx, cy = w / 2.0, h / 2.0
    rad = np.deg2rad(-angle)
    cos_a, sin_a = np.cos(rad), np.sin(rad)
    x, y, bw, bh = row[:4]
    corners = np.array([[x, y], [x + bw, y], [x, y + bh], [x + bw, y + bh]])
    dx, dy = corners[:, 0] - cx, corners[:, 1] - cy
    mapped = np.stack([cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a], axis=1)
    x0, y0 = mapped.min(axis=0)
    x1, y1 = mapped.max(axis=0)
    return np.array([x0, y0, x1 - x0, y1 - y0], dtype=np.float32)


class FaceEngine:
    def __init__(self, models_dir, det_score=0.8, max_side=1280, auto_brighten=True):
        models = Path(models_dir)
        self.detector = cv2.FaceDetectorYN.create(
            str(models / "face_detection_yunet_2023mar.onnx"), "", (320, 320), det_score, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(models / "face_recognition_sface_2021dec.onnx"), "")
        self.det_score = det_score
        self.max_side = max_side
        self.auto_brighten = auto_brighten
        self.lock = threading.Lock()  # cv2 DNN objects are not thread-safe

    def analyze(self, img: np.ndarray, det_score: float | None = None) -> list[FaceObs]:
        """All faces in the image with embeddings, largest first."""
        h, w = img.shape[:2]
        scale = min(1.0, self.max_side / max(h, w))
        work = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img
        if self.auto_brighten:
            work = brighten(work)
        with self.lock:
            self.detector.setScoreThreshold(self.det_score if det_score is None else det_score)
            self.detector.setInputSize((work.shape[1], work.shape[0]))
            _, rows = self.detector.detect(work)
            source, angle = work, 0
            if rows is None or len(rows) == 0:
                for candidate_angle in TILT_FALLBACK_DEG:
                    rows, rotated = _rotated_detect(self.detector, work, candidate_angle)
                    if rows is not None and len(rows):
                        source, angle = rotated, candidate_angle
                        break
            out = []
            for row in (rows if rows is not None else []):
                feat = self.recognizer.feature(self.recognizer.alignCrop(source, row))[0]
                feat = feat / (np.linalg.norm(feat) + 1e-9)
                box = row[:4] if angle == 0 else _box_from_rotated(row, angle, work.shape)
                x, y, bw, bh = (box / scale).tolist()
                out.append(FaceObs((x, y, bw, bh), float(row[14]), feat.astype(np.float32)))
        out.sort(key=lambda f: f.box[2] * f.box[3], reverse=True)
        return out

    def enrol_embeddings(self, img: np.ndarray) -> np.ndarray:
        """Embeddings of the largest face in a reference photo plus its mirror (robustness with sparse photos)."""
        faces = self.analyze(img, det_score=0.7)  # reference photos are deliberate, be lenient
        if not faces:
            raise ValueError("no face found in the reference image")
        embs = [faces[0].embedding]
        mirrored = self.analyze(cv2.flip(img, 1), det_score=0.7)
        if mirrored:
            embs.append(mirrored[0].embedding)
        return np.stack(embs)

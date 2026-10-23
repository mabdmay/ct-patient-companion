import argparse
import base64
import binascii
import copy
import json
import logging
import mimetypes
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

import cv2
import numpy as np

from positioning.arms import ArmRules, POSTURES
from positioning.camera import IMAGE_SUFFIXES, utc_now
from positioning.config import build_table, load_config
from positioning.geometry import assess_position
from positioning.integration import make_event
from positioning.perception import YoloPoseBackend
from positioning.visualization import PANEL_HEIGHT, annotate


ROOT = Path(__file__).resolve().parent
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_BODY_BYTES = 17 * 1024 * 1024


class AnalysisService:
    def __init__(self, backend_factory=YoloPoseBackend):
        self.profiles = {
            "supplied": ("Supplied photo camera (demo)", ROOT / "config.data.yaml"),
            "unconfigured": ("New camera / unconfirmed", ROOT / "config.yaml"),
        }
        self.backend_factory = backend_factory
        self.backends = {}
        self.lock = threading.Lock()
        self.samples = sorted(path for path in (ROOT / "data").glob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)

    def settings(self) -> dict:
        profiles = []
        for identifier, (label, path) in self.profiles.items():
            config, rules = load_config(path)
            profiles.append({
                "id": identifier, "label": label, "table": config["table"],
                "allowed_postures": None if rules.arm_rules is None else rules.arm_rules.allowed_postures,
                "reference_id": config["reference_id"],
            })
        return {"profiles": profiles, "samples": [{"id": index, "name": path.name} for index, path in enumerate(self.samples)]}

    def analyze(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Request must be a JSON object")
        identifier = payload.get("profile", "supplied")
        if not isinstance(identifier, str) or identifier not in self.profiles:
            raise ValueError("Unknown camera profile")
        encoded = payload.get("image")
        if not isinstance(encoded, str) or len(encoded) > MAX_BODY_BYTES:
            raise ValueError("Provide an image of at most 12 MB")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Invalid image encoding") from error
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("Provide an image of at most 12 MB")
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or min(frame.shape[:2]) < 16:
            raise ValueError("Image could not be decoded or is too small")
        if frame.shape[0] * frame.shape[1] > 20_000_000:
            raise ValueError("Image exceeds 20 megapixels; resize it before uploading")
        _, config_path = self.profiles[identifier]
        config, rules = load_config(config_path)
        config = copy.deepcopy(config)
        if "table" in payload:
            table = payload["table"]
            if not isinstance(table, dict) or type(table.get("confirmed")) is not bool or type(table.get("near_nadir")) is not bool:
                raise ValueError("Bed reference confirmation must be boolean")
            config["table"]["corners_normalized"] = table.get("corners_normalized")
            config["table"]["confirmed"] = table["confirmed"]
            config["table"]["near_nadir"] = table["near_nadir"]
            config["reference_id"] += "_ui_bed"
        table = build_table(config, frame.shape)
        if "allowed_postures" in payload:
            allowed = payload["allowed_postures"]
            if allowed is not None and (not isinstance(allowed, list) or not allowed or any(not isinstance(label, str) or label not in POSTURES for label in allowed)):
                raise ValueError("Invalid allowed arm posture")
            rules = replace(rules, arm_rules=replace(rules.arm_rules or ArmRules(), allowed_postures=None if allowed is None else tuple(allowed)))
            config["reference_id"] += "_arms_" + ("observe" if allowed is None else "_".join(allowed).lower())
        acquired = utc_now()
        started = perf_counter()
        model_key = json.dumps(config["model"], sort_keys=True)
        with self.lock:
            if model_key not in self.backends:
                self.backends[model_key] = self.backend_factory(config["model"], config_path.parent, config["table"]["corners_normalized"])
            backend = self.backends[model_key]
            backend.bed_corners = config["table"]["corners_normalized"]
            inference_started = perf_counter()
            detections = backend.detect(frame)
            inference_ms = (perf_counter() - inference_started) * 1000
        assessment = assess_position(detections, table, rules)
        rendered = annotate(frame, detections, table, rules, assessment, (perf_counter() - started) * 1000)
        success, image = cv2.imencode(".jpg", rendered[PANEL_HEIGHT:], [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not success:
            raise RuntimeError("Could not encode annotated image")
        event = make_event(assessment, config, acquired, 0, None, inference_ms, (perf_counter() - started) * 1000, False)
        return {
            "event": event, "annotation": base64.b64encode(image).decode("ascii"),
            "limits": {"lateral_fraction": rules.max_lateral_fraction, "angle_deg": rules.max_angle_deg,
                       "longitudinal_fraction": rules.max_longitudinal_fraction if rules.reference_y_fraction is not None else None},
            "table": config["table"], "model": Path(config["model"]["weights"]).name,
        }


def make_handler(service: AnalysisService):
    class Handler(BaseHTTPRequestHandler):
        def allowed_request(self):
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            return (self.headers.get("Host") in hosts
                    and (origin is None or origin in {f"http://{host}" for host in hosts})
                    and self.headers.get("Sec-Fetch-Site") != "cross-site")

        def respond(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, status, body):
            self.respond(status, json.dumps(body, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            if not self.allowed_request():
                self.json_response(403, {"error": "Local same-origin access only"})
                return
            path = urlsplit(self.path).path
            if path == "/api/settings":
                self.json_response(200, service.settings())
                return
            if path.startswith("/api/sample/"):
                try:
                    index = int(path.rsplit("/", 1)[1])
                    if index < 0:
                        raise ValueError
                    sample = service.samples[index]
                    self.respond(200, sample.read_bytes(), mimetypes.guess_type(sample.name)[0] or "image/jpeg")
                except (ValueError, IndexError):
                    self.json_response(404, {"error": "Sample not found"})
                return
            assets = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/lucide.min.js": "lucide.min.js"}
            if path not in assets or not (ROOT / "web" / assets[path]).is_file():
                self.json_response(404, {"error": "Not found"})
                return
            asset = ROOT / "web" / assets[path]
            content_type = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}[asset.suffix]
            self.respond(200, asset.read_bytes(), content_type + "; charset=utf-8")

        def do_POST(self):
            if not self.allowed_request():
                self.json_response(403, {"error": "Local same-origin access only"})
                return
            if self.path != "/api/analyze":
                self.json_response(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY_BYTES:
                    self.json_response(413, {"error": "Image request is too large or empty"})
                    return
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Use application/json")
                payload = json.loads(self.rfile.read(length))
                self.json_response(200, service.analyze(payload))
            except (ValueError, TypeError, KeyError, cv2.error):
                self.json_response(400, {"error": "Invalid image or bed settings. Check the image and selected region."})
            except (OSError, RuntimeError) as error:
                logging.error("Analysis unavailable: %s", error)
                self.json_response(503, {"error": "Analysis unavailable. Check local model weights and server logs."})

        def log_message(self, format, *args):
            logging.info(format, *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Local advisory image-review UI")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65525:
        parser.error("Port must be between 1024 and 65525")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    service = AnalysisService()
    for port in range(args.port, args.port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(service))
            break
        except OSError as error:
            if getattr(error, "winerror", None) != 10048 and error.errno != 98:
                raise
    else:
        raise SystemExit("No available port in the requested range")
    logging.info("Position review: http://127.0.0.1:%d", server.server_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
import base64
import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import cv2

from positioning.demo import synthetic_frames
from ui import AnalysisService, make_handler


class UiTests(unittest.TestCase):
    def setUp(self):
        frame, detections = next(synthetic_frames())
        _, encoded = cv2.imencode(".png", frame.image)
        self.image = base64.b64encode(encoded).decode("ascii")
        backend = Mock()
        backend.detect.return_value = detections
        self.factory = Mock(return_value=backend)
        self.service = AnalysisService(self.factory)
        self.table = {"corners_normalized": [[0.2, 0.05], [0.8, 0.05], [0.8, 0.95], [0.2, 0.95]], "confirmed": True, "near_nadir": True}

    def payload(self):
        return {"image": self.image, "profile": "supplied", "table": self.table, "allowed_postures": None}

    def test_pipeline_reuse_and_model_cache(self):
        result = self.service.analyze(self.payload())
        self.assertEqual(result["event"]["status"], "WITHIN_CRITERIA")
        self.assertTrue(result["event"]["advisory_only"])
        self.assertTrue(base64.b64decode(result["annotation"]))
        self.service.analyze(self.payload())
        self.factory.assert_called_once()
        json.dumps(result, allow_nan=False)

    def test_unconfirmed_geometry_stays_uncertain(self):
        payload = self.payload()
        payload["table"]["confirmed"] = False
        self.assertEqual(self.service.analyze(payload)["event"]["status"], "UNCERTAIN")

    def test_bad_requests_do_not_run_inference(self):
        for update in [{"image": "not-base64"}, {"image": ""}, {"profile": "unknown"}, {"allowed_postures": []}, {"allowed_postures": ["anything"]}, {"table": {"confirmed": "yes"}}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.service.analyze(self.payload() | update)
        self.factory.assert_not_called()

    def test_http_origin_and_json_validation(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            connection.request("GET", "/api/settings")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["profiles"])
            connection.request("POST", "/api/analyze", "{}", {"Content-Type": "application/json", "Origin": "https://untrusted.example"})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.request("POST", "/api/analyze", "not json", {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
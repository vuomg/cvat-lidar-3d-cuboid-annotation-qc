"""Test cvat_client / cvat_setup voi CVAT gia (may chu HTTP trong tien trinh), khong can CVAT that."""
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cuboidqc.cvat import client as cc  # noqa: E402
from cuboidqc.cvat import setup as cs  # noqa: E402


class FakeCvat(BaseHTTPRequestHandler):
    log = []
    polls = 0

    def _send(self, code, obj=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/vnd.cvat+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n)

    def _record(self, body):
        FakeCvat.log.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})

    def do_GET(self):
        self._record(b"")
        p = self.path.split("?")[0]
        if p == "/api/users/self":
            return self._send(200, {"username": "tester"})
        if p == "/api/projects":
            return self._send(200, {"count": 0, "next": None, "results": []})
        if p == "/api/labels":
            if "page=1" in self.path:
                return self._send(200, {"next": "x", "results": [{"id": 1, "name": "Car", "attributes": [{"id": 11, "name": "qc_issue"}]}]})
            return self._send(200, {"next": None, "results": [{"id": 2, "name": "Pedestrian", "attributes": []}]})
        if p.startswith("/api/requests/"):
            FakeCvat.polls += 1
            return self._send(200, {"status": "started" if FakeCvat.polls < 2 else "finished"})
        if p == "/api/jobs":
            return self._send(200, {"next": None, "results": [{"id": 7}]})
        if p.endswith("/annotations"):
            return self._send(200, {"shapes": [], "tracks": []})
        self._send(404, {"detail": "no"})

    def do_POST(self):
        body = self._body()
        self._record(body)
        if self.path == "/api/auth/login":
            return self._send(200, {"key": "SECRETKEY"})
        if self.path.startswith("/api/tasks/") and self.path.endswith("/data"):
            return self._send(202, {"rq_id": "rq-1"})
        if self.path == "/api/projects":
            return self._send(201, {"id": 5})
        if self.path == "/api/tasks":
            return self._send(201, {"id": 9})
        self._send(404, {"detail": "no"})

    def do_PUT(self):
        self._record(self._body())
        self._send(200, {})

    def do_PATCH(self):
        self._record(self._body())
        self._send(200, {})

    def do_DELETE(self):
        self._record(b"")
        self._send(204)

    def log_message(self, *a):
        pass


class TestClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeCvat)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        FakeCvat.log.clear()
        FakeCvat.polls = 0
        self.c = cc.Client("http://127.0.0.1:%d" % self.port)

    def test_login_sets_token_header(self):
        self.c.login("u", "p")
        self.assertEqual(self.c.token, "SECRETKEY")
        self.assertEqual(self.c.me()["username"], "tester")
        self.assertEqual(FakeCvat.log[-1]["headers"]["Authorization"], "Token SECRETKEY")
        login_req = FakeCvat.log[0]
        self.assertNotIn("Authorization", login_req["headers"])          # dang nhap khong gui token cu
        self.assertEqual(json.loads(login_req["body"]), {"username": "u", "password": "p"})

    def test_from_env_prefers_token_and_never_logs_in(self):
        old = {k: os.environ.get(k) for k in ("CVAT_TOKEN", "CVAT_USER", "CVAT_PASS", "CVAT_HOST")}
        try:
            os.environ.update(CVAT_TOKEN="TOK", CVAT_HOST="http://127.0.0.1:%d" % self.port)
            c = cc.Client.from_env()
            self.assertEqual(c.token, "TOK")
            self.assertFalse(FakeCvat.log)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_from_env_without_credentials_exits(self):
        old = {k: os.environ.pop(k, None) for k in ("CVAT_TOKEN", "CVAT_USER", "CVAT_PASS")}
        try:
            with self.assertRaises(SystemExit):
                cc.Client.from_env()
        finally:
            for k, v in old.items():
                if v is not None:
                    os.environ[k] = v

    def test_paged_collects_all_pages(self):
        labels = self.c.labels(project_id=5)
        self.assertEqual([l["name"] for l in labels], ["Car", "Pedestrian"])

    def test_upload_data_multipart_and_polls_until_finished(self):
        self.c.token = "T"
        res = self.c.upload_task_data(9, [("frames.zip", b"ZIPBYTES")], poll=0.01)
        self.assertEqual(res["status"], "finished")
        post = next(r for r in FakeCvat.log if r["method"] == "POST" and r["path"].endswith("/data"))
        self.assertTrue(post["headers"]["Content-Type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="client_files[0]"; filename="frames.zip"', post["body"])
        self.assertIn(b"ZIPBYTES", post["body"])
        self.assertIn(b'name="image_quality"', post["body"])
        self.assertGreaterEqual(FakeCvat.polls, 2)

    def test_patch_sends_action_param(self):
        self.c.patch_annotations(7, "update", {"tracks": []})
        r = FakeCvat.log[-1]
        self.assertEqual((r["method"], r["path"]), ("PATCH", "/api/jobs/7/annotations?action=update"))

    def test_http_error_raises_cvaterror(self):
        with self.assertRaises(cc.CvatError) as ctx:
            self.c.get("/api/nope")
        self.assertEqual(ctx.exception.status, 404)


class TestSetup(unittest.TestCase):
    def test_make_zip_only_pcd_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("000002.pcd", "000000.pcd", "notes.txt", "000001.pcd"):
                with open(os.path.join(d, n), "wb") as f:
                    f.write(b"x")
            data = cs.make_zip(d)
            import io
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertEqual(names, ["000000.pcd", "000001.pcd", "000002.pcd"])

    def test_build_payload(self):
        neutral = {"tracks": [{"key": "a", "label": "Car", "shapes": [
            {"frame": 3, "points": [1] * 16, "occluded": False, "outside": True},
            {"frame": 1, "points": [2] * 16, "occluded": True, "outside": False}]}]}
        p = cs.build_payload(neutral, {"Car": 42})
        t = p["tracks"][0]
        self.assertEqual((t["label_id"], t["frame"]), (42, 1))                  # frame cua track = frame nho nhat
        self.assertEqual([s["frame"] for s in t["shapes"]], [1, 3])
        self.assertTrue(all(s["type"] == "cuboid" and len(s["points"]) == 16 for s in t["shapes"]))
        self.assertTrue(t["shapes"][0]["occluded"] and t["shapes"][1]["outside"])

    def test_label_maps(self):
        ids, attrs = cs.label_maps([{"id": 1, "name": "Car", "attributes": [{"id": 5, "name": "qc_issue"}]}])
        self.assertEqual(ids, {"Car": 1})
        self.assertEqual(attrs, {("Car", "qc_issue"): 5})


if __name__ == "__main__":
    unittest.main()

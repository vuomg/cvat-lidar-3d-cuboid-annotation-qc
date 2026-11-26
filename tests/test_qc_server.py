"""Test qc_server: xac thuc, cache frame, luong /qc day du, CORS, va chay tren du lieu demo that (neu co)."""
import json
import math
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cuboidqc.cvat import adapter as ca  # noqa: E402
from cuboidqc.core import pcdio as pcdio  # noqa: E402
from cuboidqc.server import app as qs  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
TOKEN = "s3cret-token"
PROFILE = {"size_ranges": {}, "pts_expect": [], "size_median": {}}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

LABELS = [
    {"id": 1, "name": "Car", "attributes": [{"id": 11, "name": "qc_issue"}, {"id": 12, "name": "qc_note"}]},
    {"id": 2, "name": "Pedestrian", "attributes": [{"id": 21, "name": "qc_issue"}, {"id": 22, "name": "qc_note"}]},
    {"id": 9, "name": "QC_SUGGESTION", "attributes": [{"id": 91, "name": "issue"}, {"id": 92, "name": "target"},
                                                      {"id": 93, "name": "note"}]},
]


def shape(frame, x, y, yaw=0.0, size=(2.0, 4.0, 1.6), z=0.8, **kw):
    s = {"type": "cuboid", "frame": frame, "points": ca.box_to_points([x, y, z], size, yaw), "occluded": False,
         "outside": False, "z_order": 0, "rotation": 0.0, "attributes": []}
    s.update(kw)
    return s


def cloud(rng, center, size_wlh, n=300):
    w, l, h = size_wlh
    u, v = rng.uniform(-l / 2, l / 2, n), rng.uniform(-w / 2, w / 2, n)
    z = rng.uniform(center[2] - h / 2 + 0.25, center[2] + h / 2, n)
    return np.stack([center[0] + u, center[1] + v, z], axis=1)


def pcd_of(P):
    return pcdio.pcd_bytes(np.column_stack([P, np.full(len(P), 5.0)]))


class Http:
    def __init__(self, port):
        self.base = "http://127.0.0.1:%d" % port

    def call(self, method, path, body=None, token=TOKEN, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = dict(headers or {})
        if token is not None:
            h["X-QC-Token"] = token
        if raw is None and body is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null"), dict(e.headers)


class ServerCase(unittest.TestCase):
    service_kwargs = {}

    @classmethod
    def setUpClass(cls):
        cls.service = qs.QcService(PROFILE, **cls.service_kwargs)
        cls.httpd = qs.serve(cls.service, TOKEN, port=0, allow_origins=("http://localhost:8080",), quiet=True)
        cls.http = Http(cls.httpd.server_address[1])
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()


class TestAuthAndCache(ServerCase):
    def test_health_open_but_never_leaks_token(self):
        code, body, _ = self.http.call("GET", "/health", token=None)
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertNotIn(TOKEN, json.dumps(body))

    def test_other_routes_require_token(self):
        self.assertEqual(self.http.call("GET", "/frames?job=j", token=None)[0], 401)
        self.assertEqual(self.http.call("GET", "/frames?job=j", token="sai")[0], 401)
        self.assertEqual(self.http.call("POST", "/qc", {"job": "j"}, token=None)[0], 401)
        self.assertEqual(self.http.call("PUT", "/frames/0?job=j", raw=b"x", token="sai")[0], 401)

    def test_frame_upload_and_status(self):
        pcd = pcd_of(np.random.default_rng(0).uniform(-5, 5, (100, 3)))
        code, body, _ = self.http.call("PUT", "/frames/3?job=jobA", raw=pcd)
        self.assertEqual((code, body["points"]), (200, 100))
        code, body, _ = self.http.call("GET", "/frames?job=jobA")
        self.assertEqual(body["have"], {"3": len(pcd)})
        self.assertEqual(self.http.call("GET", "/frames?job=otherjob")[1]["have"], {})   # cache tach theo job

    def test_rejection_of_large_upload_returns_status_not_network_error(self):
        """Tu choi (sai token / sai duong dan / thieu job) mot PUT LON phai tra ma loi, khong de ket noi bi reset.
        Truoc day server tra loi ma chua doc het than yeu cau nen thinh thoang ben goi nhan loi mang."""
        big = b"x" * (3 * 1024 * 1024)
        for _ in range(12):
            self.assertEqual(self.http.call("PUT", "/frames/0?job=j", raw=big, token="sai")[0], 401)
            self.assertEqual(self.http.call("PUT", "/frames/abc?job=j", raw=big)[0], 404)
            self.assertEqual(self.http.call("PUT", "/frames/0", raw=big)[0], 400)             # thieu job

    def test_bad_pcd_and_bad_route(self):
        self.assertEqual(self.http.call("PUT", "/frames/0?job=j", raw=b"khong phai pcd")[0], 400)
        self.assertEqual(self.http.call("PUT", "/frames/abc?job=j", raw=b"x")[0], 404)
        self.assertEqual(self.http.call("PUT", "/frames/0", raw=b"x")[0], 400)             # thieu job
        self.assertEqual(self.http.call("GET", "/nope")[0], 404)

    def test_invalid_json_and_policy_are_400_not_500(self):
        self.assertEqual(self.http.call("POST", "/qc", raw=b"{khong phai json")[0], 400)
        body = {"job": "j", "annotations": {"shapes": [], "tracks": []}, "labels": LABELS, "frame_names": [],
                "apply_policy": "bua-bai"}
        self.assertEqual(self.http.call("POST", "/qc", body)[0], 400)

    def test_cors_only_for_allowed_origin(self):
        _, _, h = self.http.call("GET", "/health", headers={"Origin": "http://localhost:8080"})
        self.assertEqual(h.get("Access-Control-Allow-Origin"), "http://localhost:8080")
        _, _, h = self.http.call("GET", "/health", headers={"Origin": "http://evil.example"})
        self.assertIsNone(h.get("Access-Control-Allow-Origin"))
        code, _, h = self.http.call("OPTIONS", "/qc", headers={"Origin": "http://localhost:8080"}, token=None)
        self.assertEqual(code, 204)
        self.assertIn("X-QC-Token", h.get("Access-Control-Allow-Headers", ""))


class TestQcFlow(ServerCase):
    def setUp(self):
        self.rng = np.random.default_rng(7)
        # 3 frame; frame 1 co xe ghi lech ngang 1.6 m; frame 0 va 2 dung
        self.ann = {"version": 0, "tags": [], "shapes": [], "tracks": [{
            "id": 5, "label_id": 1, "frame": 0, "attributes": [],
            "shapes": [shape(0, 10, 0), shape(1, 10, 1.6), shape(2, 10, 0)]}]}
        self.job = "job-%d" % id(self)
        self.clouds = {i: cloud(self.rng, (10, 0, 0.8), (2, 4, 1.6)) for i in range(3)}

    def upload_all(self):
        for i, P in self.clouds.items():
            self.assertEqual(self.http.call("PUT", "/frames/%d?job=%s" % (i, self.job), raw=pcd_of(P))[0], 200)

    def request(self, **kw):
        body = {"job": self.job, "annotations": self.ann, "labels": LABELS,
                "frame_names": ["000000.pcd", "000001.pcd", "000002.pcd"]}
        body.update(kw)
        return self.http.call("POST", "/qc", body)

    def test_reports_missing_frames_then_succeeds_after_upload(self):
        code, body, _ = self.request()
        self.assertEqual((code, body["missing_frames"]), (200, [0, 1, 2]))
        self.upload_all()
        code, body, _ = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(body["missing_frames"], [])
        self.assertEqual(body["summary"]["flagged"], 1)
        it = body["items"][0]
        self.assertEqual((it["track_id"], it["frame"], it["label"]), (5, 1, "Car"))
        self.assertEqual(it["pos"], [10.0, 1.6, 0.8])             # toa do box (x, y, z) de nguoi dung dinh vi
        self.assertEqual(it["dist"], 10.1)                        # khoang cach toi xe
        self.assertIn("BOX_OFFSET", it["issues"])
        self.assertEqual(it["fix"]["kind"], "refit")
        self.assertFalse(it["fix"]["auto"])                       # conservative: khong tu dich box

    def test_plan_writes_flag_and_suggestion(self):
        self.upload_all()
        _, body, _ = self.request()
        self.assertTrue(body["can_write"])
        plan = body["plan"]
        sug = plan["create"]["shapes"]
        self.assertEqual(len(sug), 1)
        self.assertEqual(sug[0]["label_id"], 9)
        self.assertAlmostEqual(sug[0]["points"][1], 0.0, delta=0.26)            # goi y dua box ve dung cho
        upd = plan["update"]["tracks"][0]["shapes"][1]
        self.assertEqual(next(a["value"] for a in upd["attributes"] if a["spec_id"] == 11).split()[1], "BOX_OFFSET")

    def test_apply_policy_conservative_keeps_refit_for_human(self):
        self.upload_all()
        _, body, _ = self.request(apply=True)
        self.assertEqual((body["stats"]["applied"], body["stats"]["skipped"]), (0, 1))
        _, body, _ = self.request(apply=True, apply_policy="all")
        self.assertEqual(body["stats"]["applied"], 1)

    def test_missing_suggestion_label_blocks_writing_but_not_reporting(self):
        self.upload_all()
        labels = [l for l in LABELS if l["name"] != "QC_SUGGESTION"]
        _, body, _ = self.request(labels=labels)
        self.assertFalse(body["can_write"])
        self.assertTrue(any("QC_SUGGESTION" in w for w in body["warnings"]))
        self.assertEqual(body["summary"]["flagged"], 1)               # van bao loi duoc
        self.assertEqual(body["plan"]["create"]["shapes"], [])

    def test_missing_label_attributes_reported(self):
        self.upload_all()
        labels = [dict(l, attributes=[]) if l["name"] == "Car" else l for l in LABELS]
        _, body, _ = self.request(labels=labels)
        self.assertFalse(body["can_write"])
        self.assertTrue(any("Car" in w and "qc_issue" in w for w in body["warnings"]))

    def test_no_ego_pose_warns_about_heading(self):
        self.upload_all()
        _, body, _ = self.request()
        self.assertTrue(any("HEADING_REVERSED" in w for w in body["warnings"]))

    def test_allow_missing_runs_without_points(self):
        code, body, _ = self.request(allow_missing=True)
        self.assertEqual(code, 200)
        self.assertTrue(any("point cloud" in w for w in body["warnings"]))
        self.assertEqual(body["summary"]["flagged"], 0)               # khong co diem -> khong ket luan BOX_OFFSET

    def test_cache_is_reused_across_requests(self):
        self.upload_all()
        self.request()
        code, have, _ = self.http.call("GET", "/frames?job=%s" % self.job)
        self.assertEqual(sorted(have["have"]), ["0", "1", "2"])


class TestGlobalCoords(unittest.TestCase):
    def test_global_coords_enables_heading(self):
        svc = qs.QcService(PROFILE, coords="global", frame_dt=0.5)
        frames = svc.build_frames(["a", "b", "c"])
        self.assertTrue(all("ego_translation" in f for f in frames))
        self.assertEqual([f["timestamp"] for f in frames], [0, 500000, 1000000])
        ann = {"shapes": [], "tracks": [{"id": 1, "label_id": 1, "frame": 0, "attributes": [], "shapes": [
            shape(i, 10 + 2.5 * i, 0, yaw=math.pi) for i in range(3)]}]}      # chay +x 5 m/s nhung yaw nguoc
        for i in range(3):
            svc.cache.put("j", i, 1, np.zeros((0, 3)))
        out = svc.run({"job": "j", "annotations": ann, "labels": LABELS, "frame_names": ["a", "b", "c"]})
        self.assertTrue(any("HEADING_REVERSED" in it["issues"] for it in out["items"]))

    def test_ego_without_meta_has_no_ego(self):
        frames = qs.QcService(PROFILE).build_frames(["a"])
        self.assertNotIn("ego_translation", frames[0])


class TestToken(unittest.TestCase):
    def test_token_is_created_once_and_reused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".qc_token")
            t1 = qs.load_or_create_token(p)
            self.assertGreaterEqual(len(t1), 16)
            self.assertEqual(qs.load_or_create_token(p), t1)            # lan sau giong lan dau
            with open(p, "w") as f:
                f.write("  \n")                                           # file rong -> sinh moi
            t2 = qs.load_or_create_token(p)
            self.assertGreaterEqual(len(t2), 16)
            with open(p) as f:
                self.assertEqual(f.read().strip(), t2)


class TestFrameCache(unittest.TestCase):
    def test_lru_eviction_by_bytes(self):
        c = qs.FrameCache(max_bytes=2 * 24 * 100)                    # vua 2 frame 100 diem
        for i in range(3):
            c.put("j", i, 10, np.zeros((100, 3)))
        self.assertIsNone(c.get("j", 0))                              # cu nhat bi bo
        self.assertIsNotNone(c.get("j", 1))
        c.get("j", 1)                                                 # truy cap lai -> thanh moi nhat
        c.put("j", 3, 10, np.zeros((100, 3)))
        self.assertIsNone(c.get("j", 2))
        self.assertIsNotNone(c.get("j", 1))

    def test_replace_same_key_does_not_leak_size(self):
        c = qs.FrameCache(max_bytes=10 ** 9)
        c.put("j", 0, 10, np.zeros((100, 3)))
        c.put("j", 0, 10, np.zeros((100, 3)))
        self.assertEqual(c.size, 24 * 100)


@unittest.skipUnless(os.path.exists(os.path.join(ROOT, "data", "demo_data", "annotations.json"))
                     and os.path.exists(os.path.join(ROOT, "configs", "profile.json")), "can data/demo_data va configs/profile.json")
class TestDemoThroughServer(unittest.TestCase):
    """Chay qua HTTP tren du lieu demo that: phai bat 9/9 loi chen, giong cvat_qc.analyze_job."""

    def test_demo_catches_all_injected(self):
        from cuboidqc.cvat import demo as cvat_demo
        from cuboidqc.cvat import runner as cq
        from cuboidqc.cvat import setup as cs
        from cuboidqc.evaluation import cvat_loop as ev
        demo = os.path.join(ROOT, "data", "demo_data")
        meta = _load(os.path.join(demo, "meta.json"))
        labels_spec = _load(os.path.join(demo, "labels.json"))
        neutral = _load(os.path.join(demo, "annotations.json"))
        label_ids, attr_ids = ev._fake_ids(labels_spec)
        labels = [{"id": label_ids[l["name"]], "name": l["name"],
                   "attributes": [{"id": attr_ids[(l["name"], a["name"])], "name": a["name"]} for a in l["attributes"]]}
                  for l in labels_spec]
        ann = cs.build_payload(neutral, label_ids)
        for i, t in enumerate(ann["tracks"]):
            t["id"] = i + 1
        svc = qs.QcService(_load(os.path.join(ROOT, "configs", "profile.json")), meta)
        httpd = qs.serve(svc, TOKEN, port=0, quiet=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            http = Http(httpd.server_address[1])
            names = [f["name"] for f in meta["frames"]]
            for i, n in enumerate(names):
                with open(os.path.join(demo, "frames", n), "rb") as f:
                    self.assertEqual(http.call("PUT", "/frames/%d?job=demo" % i, raw=f.read())[0], 200)
            code, body, _ = http.call("POST", "/qc", {"job": "demo", "annotations": ann, "labels": labels,
                                                      "frame_names": names})
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(code, 200)
        self.assertEqual(body["summary"]["cuboids"], 1142)
        self.assertEqual(body["summary"]["flagged"], 27)
        self.assertEqual(body["warnings"], [])                       # co ego pose, du label, du point cloud
        # so voi cach tinh truc tiep
        res = cq.analyze_job(ann, {v: k for k, v in label_ids.items()}, meta["frames"],
                             cq.load_frames_points(demo, meta["frames"]), svc.profile)
        self.assertEqual(sorted(it["token"] for it in body["items"]), sorted(cq.summarize(res)))
        issues = {i for it in body["items"] for i in it["issues"]}
        self.assertEqual(issues, {"BAD_SIZE", "BOX_OFFSET", "HEADING_REVERSED", "LOW_LIDAR_PTS", "OVERLAP"})
        self.assertEqual(body["stats"]["suggestions"], 15)


if __name__ == "__main__":
    unittest.main()

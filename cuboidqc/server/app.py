#!/usr/bin/env python3
"""Server QC local cho extension CVAT (chi thu vien chuan + numpy).

Server KHONG can dang nhap CVAT: extension doc nhan / point cloud tu CVAT bang phien dang nhap cua nguoi dung,
gui sang day de tinh, roi tu ghi ket qua nguoc vao CVAT. Server chi tinh toan.

  python -m cuboidqc.server.app --profile profile.json [--meta demo_data/meta.json] [--port 8766] [--token ...]

API (tat ca tru /health can header X-QC-Token):
  GET  /health                      -> {ok, version, auth, coords, ...}
  GET  /frames?job=KEY              -> {have: {"<idx>": so_byte_pcd}}      (frame da co trong cache)
  PUT  /frames/<idx>?job=KEY        body = file .pcd goc                    (nap point cloud)
  POST /qc                          body = JSON {job, annotations, labels, frame_names, apply, apply_policy}
         -> {summary, items, plan, stats, warnings, can_write, missing_frames}
"""
import argparse
import hmac
import json
import os
import re
import secrets
import sys
import threading
from collections import Counter, OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cuboidqc.cvat import runner as cq
from cuboidqc import paths
from cuboidqc.core import pcdio as pcdio

VERSION = "0.1"
MAX_BODY = 96 * 1024 * 1024
REQUIRED_LABEL = "QC_SUGGESTION"
LABEL_ATTRS = ("qc_issue", "qc_note")
SUGGEST_ATTRS = ("issue", "target", "note")


class FrameCache:
    """Cache point cloud theo (job, frame), gioi han tong byte, bo cai cu nhat truoc (LRU)."""

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self.size = 0
        self.data = OrderedDict()          # (job, idx) -> (raw_nbytes, pts)
        self.lock = threading.Lock()

    def put(self, job, idx, raw_nbytes, pts):
        with self.lock:
            key = (job, idx)
            if key in self.data:
                self.size -= self.data.pop(key)[1].nbytes
            self.data[key] = (raw_nbytes, pts)
            self.size += pts.nbytes
            while self.size > self.max_bytes and len(self.data) > 1:
                _, (_, old) = self.data.popitem(last=False)
                self.size -= old.nbytes

    def get(self, job, idx):
        with self.lock:
            e = self.data.get((job, idx))
            if e is None:
                return None
            self.data.move_to_end((job, idx))
            return e[1]

    def status(self, job):
        with self.lock:
            return {str(i): e[0] for (j, i), e in self.data.items() if j == job}


class QcService:
    def __init__(self, profile, meta=None, coords="ego", frame_dt=0.5, cache_bytes=1 << 30):
        self.profile = profile if isinstance(profile, dict) else _load_json(profile)
        self.meta = {f["name"]: f for f in meta["frames"]} if meta else {}
        self.coords = coords
        self.frame_dt = frame_dt
        self.cache = FrameCache(cache_bytes)

    # ---- khung thoi gian / ego pose
    def build_frames(self, names):
        frames = []
        for i, name in enumerate(names):
            m = self.meta.get(name)
            if m:
                frames.append({"sample_token": m["sample_token"], "timestamp": m["timestamp"],
                               "ego_translation": m["ego_translation"], "ego_rotation": m["ego_rotation"]})
                continue
            f = {"sample_token": "frame%d" % i, "timestamp": int(i * self.frame_dt * 1e6)}
            if self.coords == "global":                      # nhan da o toa do global: ego = phep dong nhat
                f.update(ego_translation=[0.0, 0.0, 0.0], ego_rotation=[1.0, 0.0, 0.0, 0.0])
            frames.append(f)
        return frames

    @staticmethod
    def needed_frames(annotations):
        used = set()
        for s in annotations.get("shapes", []):
            if s.get("type") == "cuboid" and not s.get("outside"):
                used.add(s["frame"])
        for t in annotations.get("tracks", []):
            for s in t.get("shapes", []):
                if s.get("type") == "cuboid" and not s.get("outside"):
                    used.add(s["frame"])
        return sorted(used)

    @staticmethod
    def schema_problems(labels):
        """Cac label / attribute can co de GHI ket qua vao CVAT."""
        by_name = {l["name"]: l for l in labels}
        problems = []
        if REQUIRED_LABEL not in by_name:
            problems.append("Thieu label %s (can cho cuboid goi y)" % REQUIRED_LABEL)
        else:
            have = {a["name"] for a in by_name[REQUIRED_LABEL].get("attributes", [])}
            miss = [a for a in SUGGEST_ATTRS if a not in have]
            if miss:
                problems.append("Label %s thieu attribute: %s" % (REQUIRED_LABEL, ", ".join(miss)))
        for name, l in by_name.items():
            if name == REQUIRED_LABEL:
                continue
            have = {a["name"] for a in l.get("attributes", [])}
            miss = [a for a in LABEL_ATTRS if a not in have]
            if miss:
                problems.append("Label %s thieu attribute: %s" % (name, ", ".join(miss)))
        return problems

    # ---- chay QC
    def run(self, req):
        job = str(req["job"])
        annotations = req["annotations"]
        labels = req["labels"]
        names = req.get("frame_names") or []
        policy = req.get("apply_policy", "conservative")
        if policy not in ("conservative", "all"):
            raise ValueError("apply_policy khong hop le: %r" % policy)

        needed = self.needed_frames(annotations)
        missing = [i for i in needed if self.cache.get(job, i) is None]
        if missing and not req.get("allow_missing"):
            return {"missing_frames": missing}

        label_ids = {l["name"]: l["id"] for l in labels}
        attr_ids = {(l["name"], a["name"]): a["id"] for l in labels for a in l.get("attributes", [])}
        id2label = {v: k for k, v in label_ids.items()}
        frames = self.build_frames(names)
        result = cq.analyze_job(annotations, id2label, frames, lambda i: self.cache.get(job, i), self.profile)
        flagged = cq.summarize(result)
        apply = bool(req.get("apply"))
        plan = cq.plan_writeback(annotations, result, label_ids, attr_ids, apply=apply, apply_policy=policy)

        refs, sugg = result["job"]["refs"], result["sugg"]
        items = []
        for token, info in flagged.items():
            ref = refs[token]
            fxs = [sugg[(token, i)] for i in info["issues"] if (token, i) in sugg]
            fx = next((f for f in fxs if f.get("box")), fxs[0] if fxs else None)
            item = {"token": token, "kind": ref["kind"], "track_id": ref["track_id"], "shape_id": ref["shape_id"],
                    "frame": ref["frame"], "label": ref["label"], "severity": info["severity"],
                    "issues": info["issues"], "notes": info["notes"], "fix": None}
            if fx:
                item["fix"] = {"kind": fx["kind"], "text": fx["text"], "has_box": bool(fx.get("box")),
                               "auto": bool(fx.get("box")) and cq._fix_allowed(policy, fx, info)}
            items.append(item)
        items.sort(key=lambda it: (cq.SEV_ORDER[it["severity"]], it["frame"], it["token"]))

        warnings = []
        if result["job"]["anns_global"] is None:
            warnings.append("Khong co ego pose cho cac frame (--meta / --coords global): bo qua kiem tra HEADING_REVERSED")
        no_pts = [i for i in needed if self.cache.get(job, i) is None]
        if no_pts:
            warnings.append("Thieu point cloud cua %d frame: bo qua BOX_OFFSET / LOW_LIDAR_PTS o do" % len(no_pts))
        problems = self.schema_problems(labels)
        warnings += problems
        return {
            "summary": {"cuboids": len(result["job"]["anns"]), "flagged": len(items),
                        "by_issue": dict(Counter(i for it in items for i in it["issues"])),
                        "by_severity": dict(Counter(it["severity"] for it in items))},
            "items": items, "plan": plan, "stats": plan["stats"], "warnings": warnings,
            "can_write": not problems, "missing_frames": [],
        }


def make_handler(service, token, allow_origins, quiet=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "cuboid-qc/" + VERSION

        def log_message(self, fmt, *args):
            if not quiet:
                sys.stderr.write("[qc] %s\n" % (fmt % args))

        # ---- tien ich
        def _cors(self):
            origin = self.headers.get("Origin")
            if origin and origin in allow_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-QC-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
                self.send_header("Vary", "Origin")

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self):
            given = self.headers.get("X-QC-Token", "")
            return bool(token) and hmac.compare_digest(given.encode(), token.encode())

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("Body qua lon (%d byte)" % n)
            return self.rfile.read(n)

        def _guard(self, fn):
            try:
                if not self._authorized():
                    return self._send(401, {"error": "Token khong hop le (header X-QC-Token)"})
                return fn()
            except (ValueError, KeyError, TypeError, NotImplementedError) as e:
                return self._send(400, {"error": "%s: %s" % (type(e).__name__, e)})
            except Exception as e:                                   # noqa: BLE001 - tra loi thay vi dong ket noi
                return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

        # ---- route
        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/health":
                return self._send(200, {"ok": True, "version": VERSION, "auth": True, "coords": service.coords,
                                        "meta_frames": len(service.meta), "classes": sorted(service.profile["size_ranges"])})
            if url.path == "/frames":
                job = parse_qs(url.query).get("job", [""])[0]
                return self._guard(lambda: self._send(200, {"have": service.cache.status(job)}))
            self._send(404, {"error": "Khong co duong dan %s" % url.path})

        def do_PUT(self):
            url = urlparse(self.path)
            m = re.fullmatch(r"/frames/(\d+)", url.path)
            if not m:
                return self._send(404, {"error": "Khong co duong dan %s" % url.path})

            def put():
                job = parse_qs(url.query).get("job", [""])[0]
                if not job or len(job) > 200:
                    raise ValueError("Thieu / sai tham so job")
                raw = self._body()
                pts = pcdio.parse_pcd(raw)
                service.cache.put(job, int(m.group(1)), len(raw), pts)
                self._send(200, {"ok": True, "points": int(len(pts))})
            self._guard(put)

        def do_POST(self):
            if urlparse(self.path).path != "/qc":
                return self._send(404, {"error": "Khong co duong dan %s" % self.path})

            def qc():
                req = json.loads(self._body().decode("utf-8"))
                self._send(200, service.run(req))
            self._guard(qc)

    return Handler


def serve(service, token, host="127.0.0.1", port=8766, allow_origins=(), quiet=False):
    return ThreadingHTTPServer((host, port), make_handler(service, token, set(allow_origins), quiet))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--profile", default=str(paths.PROFILE), help="profile tham chieu (qcprofile.py)")
    ap.add_argument("--meta", help="meta.json (ego pose theo ten frame) de kiem tra huong, tuy chon")
    ap.add_argument("--coords", choices=["ego", "global"], default="ego",
                    help="he toa do cua nhan khi khong co --meta: ego (bo qua kiem tra huong) hoac global")
    ap.add_argument("--frame-dt", type=float, default=0.5, help="giay giua hai frame (khi khong co --meta)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--token", help="token xac thuc (mac dinh: bien QC_TOKEN, neu khong co thi doc/ tao file --token-file)")
    ap.add_argument("--token-file", default=str(paths.TOKEN_FILE),
                    help="file luu token on dinh giua cac lan chay (mac dinh .qc_token o thu muc goc)")
    ap.add_argument("--allow-origin", action="append", default=[],
                    help="CHI de thu nghiem: cho phep trang tu origin nay goi truc tiep (CORS). Extension khong can.")
    ap.add_argument("--cache-mb", type=int, default=1024)
    args = ap.parse_args()

    token = args.token or os.environ.get("QC_TOKEN") or load_or_create_token(args.token_file)
    meta = _load_json(args.meta) if args.meta else None
    service = QcService(_load_json(args.profile), meta, args.coords, args.frame_dt, args.cache_mb << 20)
    httpd = serve(service, token, args.host, args.port, args.allow_origin)
    print("QC server: http://%s:%d   (Ctrl+C de dung)" % (args.host, httpd.server_address[1]))
    print("Token    : %s" % token)
    print("Dan token vao trang Tuy chon cua extension.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_or_create_token(path):
    """Token on dinh qua cac lan chay: doc tu file neu co, khong thi sinh ngau nhien va luu lai.
    (Nguoi dung chi phai dan token vao extension mot lan.)"""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token
    token = secrets.token_urlsafe(16)
    with open(path, "w", encoding="utf-8") as f:
        f.write(token)
    return token


if __name__ == "__main__":
    main()

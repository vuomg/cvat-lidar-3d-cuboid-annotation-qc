"""Client toi thieu cho CVAT REST API (chi dung thu vien chuan).

Dang nhap lay tu BIEN MOI TRUONG, khong bao gio ghi ra file hay in ra man hinh:
  CVAT_HOST   (mac dinh http://localhost:8080)
  CVAT_TOKEN  khoa API (Authorization: Token ...)         hoac
  CVAT_USER + CVAT_PASS  (dang nhap qua /api/auth/login de lay khoa)
"""
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ACCEPT = "application/vnd.cvat+json"


class CvatError(RuntimeError):
    def __init__(self, status, method, url, body):
        super().__init__("%s %s -> HTTP %s: %s" % (method, url, status, (body or "")[:400]))
        self.status = status
        self.body = body


def multipart(fields, files):
    """fields: {ten: str}; files: [(ten_truong, ten_file, bytes)] -> (content_type, body)."""
    boundary = "----cvatqc" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode())
    for name, fn, data in files:
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                   "Content-Type: application/octet-stream\r\n\r\n" % (boundary, name, fn)).encode())
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % boundary).encode())
    return "multipart/form-data; boundary=%s" % boundary, buf.getvalue()


class Client:
    def __init__(self, host=None, token=None, timeout=120):
        self.host = (host or os.environ.get("CVAT_HOST") or "http://localhost:8080").rstrip("/")
        self.token = token
        self.timeout = timeout

    # ---- dang nhap
    @classmethod
    def from_env(cls):
        c = cls()
        c.token = os.environ.get("CVAT_TOKEN")
        if not c.token:
            user, pw = os.environ.get("CVAT_USER"), os.environ.get("CVAT_PASS")
            if not (user and pw):
                raise SystemExit("Thieu thong tin dang nhap CVAT. Dat CVAT_TOKEN, hoac CVAT_USER va CVAT_PASS "
                                 "(trong terminal cua ban, khong dua vao file).")
            c.login(user, pw)
        return c

    def login(self, username, password):
        r = self.request("POST", "/api/auth/login", {"username": username, "password": password}, auth=False)
        self.token = r["key"]
        return self.token

    # ---- HTTP
    def request(self, method, path, body=None, params=None, raw=None, content_type=None, auth=True, expect_json=True):
        url = self.host + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": ACCEPT}
        data = None
        if raw is not None:
            data, headers["Content-Type"] = raw, content_type
        elif body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        if auth and self.token:
            headers["Authorization"] = "Token " + self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                status = resp.status
        except urllib.error.HTTPError as e:
            raise CvatError(e.code, method, url, e.read().decode("utf-8", "replace")) from None
        except urllib.error.URLError as e:
            raise SystemExit("Khong ket noi duoc CVAT tai %s (%s)" % (self.host, e.reason))
        if not payload or not expect_json:
            return {"_status": status} if not payload else payload
        try:
            out = json.loads(payload)
        except ValueError:
            return payload
        if isinstance(out, dict):
            out.setdefault("_status", status)
        return out

    def get(self, path, **params):
        return self.request("GET", path, params=params or None)

    def paged(self, path, **params):
        """Lay het cac trang cua mot endpoint danh sach."""
        out, page = [], 1
        while True:
            r = self.request("GET", path, params=dict(params, page=page, page_size=100))
            out += r.get("results", [])
            if not r.get("next"):
                return out
            page += 1

    # ---- doi tuong
    def me(self):
        return self.get("/api/users/self")

    def find_project(self, name):
        return next((p for p in self.paged("/api/projects", search=name) if p["name"] == name), None)

    def create_project(self, name, labels):
        return self.request("POST", "/api/projects", {"name": name, "labels": labels})

    def delete_project(self, project_id):
        return self.request("DELETE", "/api/projects/%d" % project_id)

    def create_task(self, name, project_id):
        return self.request("POST", "/api/tasks", {"name": name, "project_id": project_id})

    def upload_task_data(self, task_id, files, wait=True, poll=1.0, max_wait=600):
        """files: [(ten_file, bytes)] (vd. mot file zip chua cac .pcd)."""
        ct, body = multipart({"image_quality": "70", "storage_method": "file_system", "sorting_method": "lexicographical"},
                             [("client_files[%d]" % i, fn, data) for i, (fn, data) in enumerate(files)])
        r = self.request("POST", "/api/tasks/%d/data" % task_id, raw=body, content_type=ct)
        rq = r.get("rq_id") if isinstance(r, dict) else None
        if not wait or not rq:
            return r
        t0 = time.time()
        while time.time() - t0 < max_wait:
            st = self.request("GET", "/api/requests/%s" % urllib.parse.quote(str(rq), safe=""))
            if st.get("status") == "finished":
                return st
            if st.get("status") == "failed":
                raise RuntimeError("Upload du lieu that bai: %s" % st.get("message"))
            time.sleep(poll)
        raise TimeoutError("Upload du lieu qua %ds" % max_wait)

    def task_jobs(self, task_id):
        return self.paged("/api/jobs", task_id=task_id)

    def labels(self, **filt):
        """Label kem thong tin attribute: [{id, name, attributes:[{id, name}]}]."""
        return self.paged("/api/labels", **filt)

    def get_annotations(self, job_id):
        return self.request("GET", "/api/jobs/%d/annotations" % job_id)

    def put_annotations(self, job_id, data):
        return self.request("PUT", "/api/jobs/%d/annotations" % job_id, data)

    def patch_annotations(self, job_id, action, data):
        return self.request("PATCH", "/api/jobs/%d/annotations" % job_id, data, params={"action": action})

    def job_url(self, task_id, job_id, frame=0):
        return "%s/tasks/%d/jobs/%d?frame=%d" % (self.host, task_id, job_id, frame)

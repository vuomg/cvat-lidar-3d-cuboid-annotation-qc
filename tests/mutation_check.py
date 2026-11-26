"""Kiem tra dot bien (mutation): pha code co chu dich, test suite phai bat duoc.

  python tests/mutation_check.py
Chay tren BAN SAO cua thu muc du an, khong sua file that.
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

MUTATIONS = [
    ("cuboidqc/core/qc.py", "return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))",
     "return math.atan2(2 * (w * z - x * y), 1 - 2 * (y * y + z * z))", "dau cua yaw_of"),
    ("cuboidqc/core/qc.py", "dz = min(za1, zb1) - max(za0, zb0)", "dz = 1.0", "bo qua chong theo truc z"),
    ("cuboidqc/core/qc.py", "if diff >= math.radians(HEADING_FLIP_DEG):", "if diff > math.radians(HEADING_FLIP_DEG) + 0.5:",
     "nguong huong lech"),
    ("cuboidqc/core/qc.py", "if n >= thr:\n        return None", "if n > thr:\n        return None", "bien nguong LiDAR (>= thanh >)"),
    ("cuboidqc/core/qc.py", "if med < MIN_EXPECTED_MEDIAN:", "if False:", "bo dieu kien trung vi qua thap"),
    ("cuboidqc/core/boxfit.py", "m &= (owner == -1) | (owner == idx)", "pass", "bo loc diem cua box khac"),
    ("cuboidqc/core/boxfit.py", "P[:, 2] >= cz - h / 2 + GROUND_CLEAR", "P[:, 2] >= cz - h / 2 - 5", "bo loc mat dat"),
    ("cuboidqc/core/boxfit.py", "if res[\"compact\"] < qc.FIT_MIN_COMPACT:", "if False:", "bo loc do gon (tuong / le duong)"),
    ("cuboidqc/cvat/adapter.py", "rz = c[\"yaw_sign\"] * (yaw - c[\"yaw_offset\"])", "rz = yaw - c[\"yaw_offset\"]", "dau yaw trong quy uoc CVAT"),
    ("cuboidqc/cvat/adapter.py", "qmul(ego_q, rotation)", "qmul(rotation, ego_q)", "thu tu nhan quaternion ego"),
    ("cuboidqc/cvat/adapter.py", "lst.sort(key=lambda x: refs[x[\"token\"]][\"frame\"])", "pass", "sap xep track theo frame"),
    ("cuboidqc/cvat/runner.py", "vel_yaw - ego_yaw.get(fr, 0.0)", "vel_yaw", "goi y huong khong tru yaw cua ego"),
    ("cuboidqc/cvat/runner.py", "if not info and not had_qc:\n            continue", "if False:\n            continue", "cap nhat thua cuboid khong co"),
    ("cuboidqc/cvat/runner.py", "delete = {\"shapes\": [s for s in ann.get(\"shapes\", []) if s[\"label_id\"] == sug_label]", "delete = {\"shapes\": []", "xoa QC_SUGGESTION cu"),
    ("cuboidqc/cvat/runner.py", "if best >= FIXED_IOU:", "if True:", "dieu kien 'da sua' (IoU voi box goc)"),
    ("cuboidqc/cvat/runner.py", "return info[\"severity\"] == \"ERROR\"\n    if fx[\"kind\"] == \"resize\":", "return True\n    if fx[\"kind\"] == \"resize\":", "apply: lat huong cung ap dung khi chi WARNING"),
    ("cuboidqc/cvat/runner.py", "return fx.get(\"basis\") == \"track\"", "return True", "apply: resize theo class cung duoc tu ap dung"),
    ("cuboidqc/cvat/runner.py", "    if policy == \"all\":\n        return True\n    if fx[\"kind\"]", "    if True:\n        return True\n    if fx[\"kind\"]", "apply: chinh sach conservative bi vo hieu (refit duoc ap dung)"),
    ("cuboidqc/core/fixes.py", "if len(others) < min_others:\n        return None", "if len(others) < 0:\n        return None", "resize theo track khong can du frame"),
    ("cuboidqc/server/app.py", "return bool(token) and hmac.compare_digest(given.encode(), token.encode())", "return True", "server: bo xac thuc token"),
    ("cuboidqc/server/app.py", "if missing and not req.get(\"allow_missing\"):", "if False:", "server: bo bao thieu frame"),
    ("cuboidqc/server/app.py", "if origin and origin in allow_origins:", "if origin:", "server: CORS mo cho moi origin"),
    ("cuboidqc/server/app.py", "while self.size > self.max_bytes and len(self.data) > 1:", "while False:", "server: cache khong gioi han"),
    ("extension/lib.js", "return ['delete', 'update', 'create'].filter", "return ['create', 'update', 'delete'].filter", "JS: thu tu PATCH"),
    ("extension/lib.js", "if (s.type === 'cuboid' && !s.outside) used.add(s.frame);\n    for", "if (s.type === 'cuboid') used.add(s.frame);\n    for", "JS: frame can nap (bo outside)"),
    ("extension/lib.js", "while (failed === null) {", "while (true) {", "JS: pool tiep tuc sau khi co loi"),
    ("extension/lib.js", "return new Array(start).fill('').concat", "return new Array(0).fill('').concat", "JS: dem ten frame khi job bat dau > 0"),
    ("extension/lib.js", "const m = (cookie || '').split(';').map((s) => s.trim()).find((s) => s.startsWith('csrftoken='));", "const m = (cookie || '').split(';').map((s) => s.trim()).find((s) => s.includes('csrftoken='));", "JS: nhan nham cookie *csrftoken"),
    ("cuboidqc/cvat/runner.py", "if qc.angle_diff(qc.yaw_of(orig[\"rotation\"]), qc.yaw_of(a[\"rotation\"])) > math.pi / 2:\n                    continue                       # IoU hinh hoc khong thay loi lat 180 do",
     "if False:\n                    continue", "box lat 180 do khong duoc tinh la da sua"),
    ("cuboidqc/core/fixes.py", "if abs(diff_deg - 180) <= 30:", "if abs(diff_deg - 180) <= -1:", "goi y lat 180"),
]


def main():
    survived = []
    for fname, old, new, label in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, "p")
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("data", "__pycache__", "node_modules", ".qc_token", ".cvat_login.xml"))
            path = os.path.join(dst, fname)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            if old not in src:
                print("?? khong tim thay doan can pha: %s / %s" % (fname, label))
                survived.append(label + " (khong ap dung duoc)")
                continue
            with open(path, "w", encoding="utf-8") as f:
                f.write(src.replace(old, new, 1))
            if fname.endswith(".js"):
                cmd = ["node", "--test", "extension/test/lib.test.js"]
            else:
                cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
            r = subprocess.run(cmd, cwd=dst, capture_output=True, text=True, shell=(os.name == "nt" and cmd[0] == "node"))
            killed = r.returncode != 0
            print("%s  %s" % ("BI BAT   " if killed else "SONG SOT ", label))
            if not killed:
                survived.append(label)
    print("\n%d/%d dot bien bi test bat" % (len(MUTATIONS) - len(survived), len(MUTATIONS)))
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()

"""Doc point cloud LIDAR_TOP cua nuScenes (thuan Python) va doi sang toa do global.

File .pcd.bin: moi diem 5 float32 (x, y, z, intensity, ring) trong he toa do cam bien lidar.
"""
import math
import os
import struct
from collections import OrderedDict

from cuboidqc.core import qc as qc


def quat_to_mat(q):
    w, x, y, z = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def _apply(R, t, p):
    return (R[0][0] * p[0] + R[0][1] * p[1] + R[0][2] * p[2] + t[0],
            R[1][0] * p[0] + R[1][1] * p[1] + R[1][2] * p[2] + t[1],
            R[2][0] * p[0] + R[2][1] * p[1] + R[2][2] * p[2] + t[2])


class Lidar:
    def __init__(self, root, version, cache_size=4):
        self.root = root
        sample_data = qc.load_table(root, version, "sample_data")
        ego = {e["token"]: e for e in qc.load_table(root, version, "ego_pose")}
        cs = {c["token"]: c for c in qc.load_table(root, version, "calibrated_sensor")}
        self.frames = {}
        for sd in sample_data:
            if sd.get("is_key_frame") and "LIDAR_TOP" in sd.get("filename", ""):
                e, c = ego[sd["ego_pose_token"]], cs[sd["calibrated_sensor_token"]]
                self.frames[sd["sample_token"]] = (sd["filename"],
                                                   quat_to_mat(e["rotation"]), e["translation"],
                                                   quat_to_mat(c["rotation"]), c["translation"])
        self._cache = OrderedDict()
        self._cache_size = cache_size

    def available(self, sample_token):
        f = self.frames.get(sample_token)
        return bool(f) and os.path.exists(os.path.join(self.root, f[0]))

    def points_global(self, sample_token):
        """List (x, y, z) trong toa do global, hoac None neu khong co file."""
        if sample_token in self._cache:
            self._cache.move_to_end(sample_token)
            return self._cache[sample_token]
        if not self.available(sample_token):
            return None
        fn, Re, te, Rc, tc = self.frames[sample_token]
        with open(os.path.join(self.root, fn), "rb") as f:
            data = f.read()
        pts = []
        for x, y, z, _i, _r in struct.iter_unpack("<5f", data[:len(data) // 20 * 20]):
            pts.append(_apply(Re, te, _apply(Rc, tc, (x, y, z))))
        self._cache[sample_token] = pts
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return pts


try:
    import numpy as np
except ImportError:        # numpy chi can cho checker BOX_OFFSET (boxfit.py)
    np = None

_CACHE = {}


def get_lidar(root, version):
    """Dung chung mot doi tuong Lidar (doc sample_data.json mat ~1 s)."""
    key = (os.path.abspath(root), version)
    if key not in _CACHE:
        _CACHE[key] = Lidar(root, version)
    return _CACHE[key]


def _points_np(self, sample_token):
    """Mang Nx3 float64 trong toa do global, hoac None neu khong co file (can numpy)."""
    cache = self.__dict__.setdefault("_np_cache", OrderedDict())
    if sample_token in cache:
        cache.move_to_end(sample_token)
        return cache[sample_token]
    if np is None or not self.available(sample_token):
        return None
    fn, Re, te, Rc, tc = self.frames[sample_token]
    with open(os.path.join(self.root, fn), "rb") as f:
        raw = np.frombuffer(f.read(), dtype="<f4")
    P = raw[:len(raw) // 5 * 5].reshape(-1, 5)[:, :3].astype(np.float64)
    P = P @ np.array(Rc).T + np.array(tc)
    P = P @ np.array(Re).T + np.array(te)
    cache[sample_token] = P
    if len(cache) > 4:
        cache.popitem(last=False)
    return P


Lidar.points_np = _points_np


def in_box(p, box):
    """box: dict translation, size (w,l,h), yaw. Tra (u, v, dz) neu nam trong, nguoc lai None."""
    cx, cy, cz = box["translation"]
    w, l, h = box["size"]
    c, s = math.cos(box["yaw"]), math.sin(box["yaw"])
    dx, dy = p[0] - cx, p[1] - cy
    u, v = dx * c + dy * s, -dx * s + dy * c
    dz = p[2] - cz
    if abs(u) <= l / 2 and abs(v) <= w / 2 and abs(dz) <= h / 2:
        return (u, v, dz)
    return None

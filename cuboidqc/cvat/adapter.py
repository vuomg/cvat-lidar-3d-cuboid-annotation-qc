"""Chuyen doi giua annotation CVAT 3D va dinh dang noi bo cua qc.py (kieu nuScenes).

Quy uoc cuboid CVAT 3D (points, 16 so):  [px, py, pz, rx, ry, rz, sx, sy, sz, 0, 0, 0, 0, 0, 0, 0]
  - vi tri, goc Euler (radian) quanh x/y/z, scale theo truc cuc bo x/y/z.
Mac dinh (cung gia dinh voi cvat-prelabel/exporter.py): huong mat truoc cua box = +x cuc bo,
sx = chieu dai (l), sy = chieu rong (w), sz = chieu cao (h), yaw = rz.
Cac gia tri nay DA KIEM CHUNG tren CVAT 2.81.1 bang cvat_calibrate.py (ket qua o CVAT_CALIBRATION.md);
rieng "dau nao la phia truoc" thi khong doc duoc tu hop doi xung nen van la gia dinh (+x).

Noi bo: size = (w, l, h) nhu nuScenes, rotation = quaternion (w, x, y, z).
"""
import math

from cuboidqc.core import qc as qc

# Ten label (8 class cua guideline) -> ten category "chuan" kieu nuScenes de dung lai cac luat cua qc.py
LABEL_TO_CANON = {
    "Car": "vehicle.car",
    "Truck": "vehicle.truck",
    "Trailer": "vehicle.trailer",
    "Bus": "vehicle.bus.rigid",
    "Construction_vehicle": "vehicle.construction",
    "Pedestrian": "human.pedestrian.adult",
    "Two_wheels": "vehicle.motorcycle",
    "Barrier": "movable_object.barrier",
}

# Ket qua hieu chinh (xem cvat_calibrate.py). Gia tri mac dinh = gia dinh cua cvat-prelabel.
CONVENTION = {
    "scale_order": "lwh",    # sx, sy, sz tuong ung (l, w, h)
    "yaw_offset": 0.0,       # yaw_noi_bo = rz + yaw_offset
    "yaw_sign": 1.0,         # +1: rz tang nguoc chieu kim dong ho (theo +z len)
}


# ------------------------------------------------------------------ hinh hoc co ban
def quat_from_yaw(yaw):
    return [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return [w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2]


def rotate(q, v):
    """Quay vector v bang quaternion q (w, x, y, z)."""
    w, x, y, z = q
    # v' = v + 2w(q x v) + 2 q x (q x v)
    cx, cy, cz = (y * v[2] - z * v[1], z * v[0] - x * v[2], x * v[1] - y * v[0])
    return [v[0] + 2 * (w * cx + y * cz - z * cy),
            v[1] + 2 * (w * cy + z * cx - x * cz),
            v[2] + 2 * (w * cz + x * cy - y * cx)]


def box_to_points(translation, size_wlh, yaw, convention=None):
    """Box noi bo -> 16 so cua cuboid CVAT."""
    c = convention or CONVENTION
    w, l, h = size_wlh
    dims = {"l": l, "w": w, "h": h}
    sx, sy, sz = (dims[k] for k in c["scale_order"])
    rz = c["yaw_sign"] * (yaw - c["yaw_offset"])
    return [translation[0], translation[1], translation[2], 0.0, 0.0, rz, sx, sy, sz] + [0.0] * 7


def points_to_box(points, convention=None):
    """16 so cua cuboid CVAT -> (translation, size_wlh, yaw)."""
    c = convention or CONVENTION
    px, py, pz, _rx, _ry, rz, sx, sy, sz = points[:9]
    dims = dict(zip(c["scale_order"], (sx, sy, sz)))
    yaw = c["yaw_sign"] * rz + c["yaw_offset"]
    yaw = (yaw + math.pi) % (2 * math.pi) - math.pi
    return [px, py, pz], (dims["w"], dims["l"], dims["h"]), yaw


def to_global(translation, rotation, ego_t, ego_q):
    """Box o he toa do ego -> he toa do global (nuScenes ego_pose: rotation quaternion w,x,y,z)."""
    p = rotate(ego_q, translation)
    return [p[0] + ego_t[0], p[1] + ego_t[1], p[2] + ego_t[2]], qmul(ego_q, rotation)


# ------------------------------------------------------------------ doc annotation CVAT
def _shape_records(annotations):
    """Duoi dang (kind, track_id, shape_id, shape_dict, label_id, group) cho moi cuboid goc (khong noi suy)."""
    recs = []
    for s in annotations.get("shapes", []):
        if s.get("type") == "cuboid" and not s.get("outside"):
            recs.append(("shape", None, s.get("id"), s, s["label_id"]))
    for t in annotations.get("tracks", []):
        for s in t.get("shapes", []):
            if s.get("type") == "cuboid" and not s.get("outside"):
                recs.append(("track", t.get("id"), None, s, t["label_id"]))
    return recs


def _attr_value(shape, label_attrs, name):
    """Gia tri attribute theo ten (label_attrs: {spec_id: ten})."""
    for a in shape.get("attributes", []) or []:
        if label_attrs.get(a.get("spec_id")) == name:
            return a.get("value")
    return None


def load_job(annotations, labels, frames=None, convention=None):
    """Doc annotation cua mot job CVAT 3D.

    annotations : JSON tra ve boi GET /api/jobs/{id}/annotations
    labels      : {label_id: ten label}
    frames      : list theo chi so frame: {"sample_token", "timestamp", "ego_translation", "ego_rotation"} (tuy chon).
                  Thieu ego -> khong tinh duoc van toc (bo kiem tra huong), annotation giu nguyen he cuc bo.
    Tra dict: anns (he cuc bo/ego), anns_global (hoac None), cats, vis, sample_ts, refs.
    refs[token] = {kind, track_id, shape_id, frame, label_id, label, occluded}
    """
    frames = frames or []
    recs = _shape_records(annotations)
    anns, anns_g, cats, refs = [], [], [], {}
    by_track = {}
    have_ego = bool(frames) and all("ego_translation" in f for f in frames)
    for kind, tid, sid, s, label_id in recs:
        label = labels.get(label_id)
        canon = LABEL_TO_CANON.get(label)
        if canon is None:                       # label khong thuoc 8 class (vd. QC_SUGGESTION) -> bo qua
            continue
        frame = s["frame"]
        token = ("t%s:%d" % (tid, frame)) if kind == "track" else ("s%s" % sid)
        t, size, yaw = points_to_box(s["points"], convention)
        meta = frames[frame] if frame < len(frames) else {}
        a = {"token": token, "sample_token": meta.get("sample_token", "frame%d" % frame),
             "instance_token": ("track%s" % tid) if kind == "track" else token,
             "translation": t, "size": list(size), "rotation": quat_from_yaw(yaw),
             "num_lidar_pts": None, "visibility_token": "occ" if s.get("occluded") else "ok",
             "prev": "", "next": ""}
        anns.append(a)
        cats.append(canon)
        refs[token] = {"kind": kind, "track_id": tid, "shape_id": sid, "frame": frame,
                       "label_id": label_id, "label": label, "occluded": bool(s.get("occluded"))}
        if kind == "track":
            by_track.setdefault(tid, []).append(a)
        if have_ego:
            gt, gq = to_global(t, a["rotation"], meta["ego_translation"], meta["ego_rotation"])
            anns_g.append(dict(a, translation=gt, rotation=gq))
    for tid, lst in by_track.items():       # prev / next theo thu tu frame trong track
        lst.sort(key=lambda x: refs[x["token"]]["frame"])
        for i, a in enumerate(lst):
            a["prev"] = lst[i - 1]["token"] if i else ""
            a["next"] = lst[i + 1]["token"] if i < len(lst) - 1 else ""
    if have_ego:
        by_tok = {a["token"]: a for a in anns}
        for g in anns_g:
            g["prev"], g["next"] = by_tok[g["token"]]["prev"], by_tok[g["token"]]["next"]
    sample_ts = {f["sample_token"]: f["timestamp"] for f in frames if "timestamp" in f}
    vis = {"occ": "v0-40", "ok": "v80-100"}
    dist = {a["token"]: math.hypot(a["translation"][0], a["translation"][1]) for a in anns}
    return {"anns": anns, "anns_global": anns_g or None, "cats": cats, "vis": vis,
            "sample_ts": sample_ts, "refs": refs, "dist": dist}

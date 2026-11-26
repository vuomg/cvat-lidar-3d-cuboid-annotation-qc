#!/usr/bin/env python3
"""Dung du lieu demo cho CVAT tu mot scene nuScenes:
  <out>/frames/000000.pcd ...   point cloud (nhi phan) trong he toa do ego, 1 file / keyframe
  <out>/meta.json               moi frame: ten file, sample_token, timestamp, ego pose (de tinh van toc)
  <out>/labels.json             dac ta label cho CVAT (8 class guideline + QC_SUGGESTION)
  <out>/annotations.json        nhan dang track (trung lap, chua co id cua CVAT)
  <out>/injected.json           so ghi cac loi CHEN VAO co chu dich (kem box goc de do IoU truoc/sau)

  python -m cuboidqc.cvat.demo --dataroot V:\\data\\nuscenes --scene scene-0553 --out demo_data
"""
import argparse
import copy
import json
import math
import os
import random
import struct

import numpy as np
from cuboidqc import paths

from cuboidqc.core import boxfit as boxfit
from cuboidqc.cvat import adapter as ca
from cuboidqc.core import lidar as lidar
from cuboidqc.core import pcdio as pcdio
from cuboidqc.core import qc as qc
from cuboidqc.core import qcprofile as qcprofile

CANON_TO_LABEL = {v: k for k, v in ca.LABEL_TO_CANON.items()}
LABEL_COLORS = {"Car": "#1f77b4", "Truck": "#ff7f0e", "Trailer": "#8c564b", "Bus": "#9467bd",
                "Construction_vehicle": "#bcbd22", "Pedestrian": "#d62728", "Two_wheels": "#17becf",
                "Barrier": "#7f7f7f", "QC_SUGGESTION": "#00e000"}
MAX_RANGE = {"Car": 50, "Truck": 50, "Trailer": 50, "Bus": 50, "Construction_vehicle": 50,
             "Pedestrian": 40, "Two_wheels": 40, "Barrier": 30}      # cvat-prelabel/configs/thresholds.json


def labels_spec():
    spec = []
    for name, color in LABEL_COLORS.items():
        if name == "QC_SUGGESTION":
            attrs = [{"name": "issue", "input_type": "text", "mutable": True, "values": [""], "default_value": ""},
                     {"name": "target", "input_type": "text", "mutable": True, "values": [""], "default_value": ""},
                     {"name": "note", "input_type": "text", "mutable": True, "values": [""], "default_value": ""}]
        else:
            attrs = [{"name": "qc_issue", "input_type": "text", "mutable": True, "values": [""], "default_value": ""},
                     {"name": "qc_note", "input_type": "text", "mutable": True, "values": [""], "default_value": ""}]
        spec.append({"name": name, "color": color, "type": "cuboid", "attributes": attrs})
    return spec


def write_pcd(path, pts):
    """pts: Nx4 float32 (x, y, z, intensity) -> PCD nhi phan."""
    n = len(pts)
    header = ("# .PCD v0.7\nVERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n"
              "WIDTH %d\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS %d\nDATA binary\n" % (n, n))
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(np.ascontiguousarray(pts, dtype="<f4").tobytes())


def read_pcd(path):
    """Doc PCD nhi phan/ascii tu duong dan -> mang Nx3 float64 (xem pcdio.parse_pcd)."""
    with open(path, "rb") as f:
        return pcdio.parse_pcd(f.read())


def _scene_samples(root, version, scene_name):
    scenes = {s["name"]: s for s in qc.load_table(root, version, "scene")}
    samples = {s["token"]: s for s in qc.load_table(root, version, "sample")}
    order, t = [], scenes[scene_name]["first_sample_token"]
    while t:
        order.append(samples[t])
        t = samples[t]["next"]
    return order


def build(root, version, scene_name, out_dir, seed=0, inject=True):
    rng = random.Random(seed)
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    order = _scene_samples(root, version, scene_name)
    tok_frame = {s["token"]: i for i, s in enumerate(order)}
    lid = lidar.get_lidar(root, version)

    # ---- frames: pcd (ego) + meta
    meta = []
    ego_of = {}
    for i, s in enumerate(order):
        fn, Re, te, Rc, tc = lid.frames[s["token"]]
        raw = np.fromfile(os.path.join(root, fn), dtype="<f4").reshape(-1, 5)
        P = raw[:, :3].astype(np.float64) @ np.array(Rc).T + np.array(tc)      # lidar -> ego
        out = np.concatenate([P, raw[:, 3:4]], axis=1).astype(np.float32)
        name = "%06d.pcd" % i
        write_pcd(os.path.join(out_dir, "frames", name), out)
        ego_q = _mat_to_quat(Re)
        ego_of[s["token"]] = (te, ego_q)
        meta.append({"name": name, "sample_token": s["token"], "timestamp": s["timestamp"],
                     "ego_translation": list(te), "ego_rotation": ego_q})

    # ---- boxes GT -> ego -> tracks
    cat = {c["token"]: c["name"] for c in qc.load_table(root, version, "category")}
    inst = {i["token"]: cat[i["category_token"]] for i in qc.load_table(root, version, "instance")}
    vis = {v["token"]: v["level"] for v in qc.load_table(root, version, "visibility")}
    anns = [a for a in qc.load_table(root, version, "sample_annotation") if a["sample_token"] in tok_frame]
    tracks = {}
    gt_info = {}                           # (track_key, frame) -> thong tin GT de chon ung vien chen loi
    for a in anns:
        canon = qcprofile.NUSCENES_TO_CANON.get(inst[a["instance_token"]])
        if not canon:
            continue
        label = CANON_TO_LABEL[canon]
        te, qe = ego_of[a["sample_token"]]
        qe_inv = [qe[0], -qe[1], -qe[2], -qe[3]]
        rel = [a["translation"][k] - te[k] for k in range(3)]
        t_ego = ca.rotate(qe_inv, rel)
        q_ego = ca.qmul(qe_inv, a["rotation"])
        if math.hypot(t_ego[0], t_ego[1]) > MAX_RANGE[label]:
            continue
        yaw = qc.yaw_of(q_ego)
        f = tok_frame[a["sample_token"]]
        tr = tracks.setdefault(a["instance_token"], {"key": a["instance_token"][:8], "label": label, "shapes": {}})
        tr["shapes"][f] = {"frame": f, "points": ca.box_to_points(t_ego, a["size"], yaw), "outside": False,
                           "occluded": vis.get(a.get("visibility_token")) == "v0-40"}
        gt_info[(tr["key"], f)] = {"pts": a.get("num_lidar_pts") or 0, "dist": math.hypot(t_ego[0], t_ego[1]),
                                   "token": a["token"]}
    out_tracks = []
    for tr in tracks.values():
        frames = sorted(tr["shapes"])
        shapes = []
        for k, f in enumerate(frames):
            shapes.append(tr["shapes"][f])
            nxt = frames[k + 1] if k + 1 < len(frames) else None
            if (nxt is None or nxt != f + 1) and f + 1 < len(order):      # ket thuc / dut doan -> 'outside'
                s = copy.deepcopy(tr["shapes"][f])
                s.update(frame=f + 1, outside=True)
                shapes.append(s)
        out_tracks.append({"key": tr["key"], "label": tr["label"], "shapes": shapes})

    injected = []
    if inject:
        injected = _inject_errors(out_tracks, gt_info, meta, rng,
                                  lambda f: read_pcd(os.path.join(out_dir, "frames", meta[f]["name"])))

    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump({"scene": scene_name, "frames": meta}, f)
    with open(os.path.join(out_dir, "labels.json"), "w") as f:
        json.dump(labels_spec(), f, indent=1)
    with open(os.path.join(out_dir, "annotations.json"), "w") as f:
        json.dump({"tracks": out_tracks}, f)
    with open(os.path.join(out_dir, "injected.json"), "w") as f:
        json.dump(injected, f, indent=1)
    return {"frames": len(order), "tracks": len(out_tracks),
            "shapes": sum(1 for t in out_tracks for s in t["shapes"] if not s["outside"]),
            "injected": len(injected)}


def _mat_to_quat(R):
    """Ma tran quay 3x3 -> quaternion (w, x, y, z)."""
    t = R[0][0] + R[1][1] + R[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return [0.25 * s, (R[2][1] - R[1][2]) / s, (R[0][2] - R[2][0]) / s, (R[1][0] - R[0][1]) / s]
    i = max(range(3), key=lambda k: R[k][k])
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(R[i][i] - R[j][j] - R[k][k] + 1.0) * 2
    q = [0.0] * 4
    q[0] = (R[k][j] - R[j][k]) / s
    q[i + 1] = 0.25 * s
    q[j + 1] = (R[j][i] + R[i][j]) / s
    q[k + 1] = (R[k][i] + R[i][k]) / s
    return q


def _speed(track, f, meta):
    """Toc do (m/s) cua track tai frame f theo toa do global (dung ego pose)."""
    shp = {s["frame"]: s for s in track["shapes"] if not s["outside"]}
    if f - 1 not in shp or f + 1 not in shp:
        return 0.0

    def g(fr):
        m = meta[fr]
        p = shp[fr]["points"]
        t, _ = ca.to_global(p[:3], [1, 0, 0, 0], m["ego_translation"], m["ego_rotation"])
        return t
    a, b = g(f - 1), g(f + 1)
    dt = (meta[f + 1]["timestamp"] - meta[f - 1]["timestamp"]) / 1e6
    return math.hypot(b[0] - a[0], b[1] - a[1]) / dt


def _inject_errors(tracks, gt_info, meta, rng, points_fn):
    """Chen loi co chu dich; tra so ghi. Moi muc: loai, track, frame, box goc (de do IoU)."""
    injected = []
    used = set()

    def shape_at(tr, f):
        return next((s for s in tr["shapes"] if s["frame"] == f and not s["outside"]), None)

    def candidates(label, min_pts, max_dist, run=1, fast=False):
        out = []
        for tr in tracks:
            if tr["label"] != label or tr["key"] in used:
                continue
            frames = [s["frame"] for s in tr["shapes"] if not s["outside"]]
            for f in frames:
                if all(shape_at(tr, f + k) and not shape_at(tr, f + k)["occluded"]
                       and gt_info.get((tr["key"], f + k), {}).get("pts", 0) >= min_pts
                       and gt_info.get((tr["key"], f + k), {}).get("dist", 99) <= max_dist
                       for k in range(run)) and (not fast or _speed(tr, f + 1, meta) >= 4.0):
                    out.append((tr, f))
        return out

    def take(label, min_pts, max_dist, run=1, fast=False):
        c = candidates(label, min_pts, max_dist, run, fast)
        if not c:
            return None
        tr, f = rng.choice(c)
        used.add(tr["key"])
        return tr, f

    def record(kind, expect, tr, f, orig, note):
        injected.append({"kind": kind, "expect_issue": expect, "track": tr["key"] if tr else None, "frame": f,
                         "original_points": orig, "note": note})

    # 1) huong nguoc: lat yaw 3 frame lien tiep cua xe dang chay nhanh
    got = take("Car", 40, 35, run=3, fast=True)
    if got:
        tr, f = got
        for k in range(3):
            s = shape_at(tr, f + k)
            orig = list(s["points"])
            s["points"][5] += math.pi
            record("heading_flip", "HEADING_REVERSED", tr, f + k, orig, "lat yaw 180 do")
    # 2) sai kich thuoc: nguoi di bo x1.7, xe dai 1.9 lan
    got = take("Pedestrian", 20, 25)
    if got:
        tr, f = got
        s = shape_at(tr, f)
        orig = list(s["points"])
        s["points"][6:9] = [x * 1.7 for x in s["points"][6:9]]
        record("size_pedestrian", "BAD_SIZE", tr, f, orig, "kich thuoc x1.7")
    got = take("Car", 40, 35)
    if got:
        tr, f = got
        s = shape_at(tr, f)
        orig = list(s["points"])
        s["points"][6] *= 1.9
        record("size_car", "BAD_SIZE", tr, f, orig, "chieu dai x1.9")
    # 3) box lech: xe lech ngang 1.6 m, nguoi lech 1.3 m
    for label, shift, min_pts, kind in (("Car", 1.6, 60, "offset_car"), ("Pedestrian", 1.3, 25, "offset_pedestrian")):
        got = take(label, min_pts, 30)
        if got:
            tr, f = got
            s = shape_at(tr, f)
            orig = list(s["points"])
            rz = s["points"][5]
            s["points"][0] += -math.sin(rz) * shift
            s["points"][1] += math.cos(rz) * shift
            record(kind, "BOX_OFFSET", tr, f, orig, "dich ngang %.1f m" % shift)
    # 4) box trung: nhan doi mot xe, dich 0.4 chieu dai theo huong
    got = take("Car", 60, 30)
    if got:
        tr, f = got
        s = shape_at(tr, f)
        d = copy.deepcopy(s)
        rz, l = s["points"][5], s["points"][6]
        d["points"][0] += math.cos(rz) * l * 0.4
        d["points"][1] += math.sin(rz) * l * 0.4
        d["frame"] = f
        dup = {"key": "dup%02d" % len(injected), "label": "Car", "shapes": [d]}
        if f + 1 < len(meta):
            e = copy.deepcopy(d)
            e.update(frame=f + 1, outside=True)
            dup["shapes"].append(e)
        tracks.append(dup)
        record("duplicate_box", "OVERLAP", dup, f, None, "box trung, dich 0.4 chieu dai")
    # 5) box ma: xe dat o noi trong, khong co diem. Dat trong 12-26 m tu xe (xa hon thi xe that cung chi co
    #    vai diem, QC khong the ket luan), va kiem tra that su khong co diem nao trong box.
    got = take("Car", 40, 30)
    if got:
        tr, f = got
        s = shape_at(tr, f)
        P = points_fn(f)
        for _ in range(200):
            ang, r = rng.uniform(0, 2 * math.pi), rng.uniform(12, 26)
            cand = copy.deepcopy(s)
            cand["points"][0], cand["points"][1] = r * math.cos(ang), r * math.sin(ang)
            t_, size_, yaw_ = ca.points_to_box(cand["points"])
            if boxfit.count_in_box(P, {"translation": t_, "size": list(size_), "rotation": ca.quat_from_yaw(yaw_)}) == 0:
                break
        else:
            cand = None
        ghost = cand
    if got and ghost:
        gt = {"key": "ghost%02d" % len(injected), "label": "Car", "shapes": [ghost]}
        if f + 1 < len(meta):
            e = copy.deepcopy(ghost)
            e.update(frame=f + 1, outside=True)
            gt["shapes"].append(e)
        tracks.append(gt)
        record("ghost_box", "LOW_LIDAR_PTS", gt, f, None, "box dat noi khong co diem")
    return injected


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--scene", default="scene-0553")
    ap.add_argument("--out", default=str(paths.DEMO))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-inject", action="store_true")
    args = ap.parse_args()
    info = build(args.dataroot, args.version, args.scene, args.out, args.seed, not args.no_inject)
    print("Da dung demo: %(frames)d frame, %(tracks)d track, %(shapes)d cuboid, %(injected)d loi chen" % info)


if __name__ == "__main__":
    main()

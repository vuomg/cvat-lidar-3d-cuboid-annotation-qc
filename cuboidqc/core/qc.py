#!/usr/bin/env python3
"""cuboid-qc MVP v0.1 - QC cuboid 3D cho nuScenes (N2-04C).

Checker:
  1. LOW_LIDAR_PTS : qua it diem LiDAR ben trong cuboid
  2. BAD_SIZE      : kich thuoc phi ly so voi class
  3. OVERLAP       : cuboid chong nhau (IoU 3D / chua nhau)
  4. HEADING_REVERSED : huong cuboid nguoc chieu di chuyen
  5. BOX_OFFSET    : box lech khoi vat the theo point cloud that (can numpy, xem boxfit.py)

Chi dung stdlib, doc thang cac bang JSON cua nuScenes (khong can nuscenes-devkit).

Dung:
  python -m cuboidqc.core.qc --dataroot <thu muc nuScenes> --version v1.0-mini --out report.csv
"""
import argparse
import csv
import json
import math
import os
from collections import Counter, defaultdict
from cuboidqc import paths

# ---- Cau hinh mac dinh (v0.3 se chuyen sang YAML) --------------------------
# Nguong diem LiDAR toi thieu theo nhom class (tien to ten category nuScenes).
MIN_PTS = {
    "vehicle": 5,
    "human": 3,
    "animal": 3,
    "movable_object": 3,
    "static_object": 3,
}
DEFAULT_MIN_PTS = 3

# Khoang kich thuoc hop ly (m) khi khong du mau de tinh tu du lieu.
# nuScenes size = (width, length, height)
# Dang ((min_w, max_w), (min_l, max_l), (min_h, max_h))
PRIOR_SIZE = {
    "vehicle.car": ((1.4, 2.4), (3.0, 6.5), (1.1, 2.4)),
    "vehicle.truck": ((2.0, 3.2), (4.0, 14.0), (1.8, 4.5)),
    "vehicle.bus.rigid": ((2.2, 3.2), (6.0, 14.0), (2.4, 4.5)),
    "vehicle.bus.bendy": ((2.2, 3.2), (10.0, 20.0), (2.4, 4.5)),
    "vehicle.construction": ((1.5, 4.0), (3.0, 12.0), (1.5, 5.0)),
    "vehicle.trailer": ((1.8, 3.2), (3.0, 20.0), (1.0, 4.8)),
    "vehicle.motorcycle": ((0.5, 1.2), (1.4, 2.8), (0.9, 2.0)),
    "vehicle.bicycle": ((0.4, 1.0), (1.2, 2.4), (0.8, 2.0)),
    "human.pedestrian.adult": ((0.2, 1.2), (0.2, 1.2), (0.9, 2.2)),
    "human.pedestrian.child": ((0.2, 1.0), (0.2, 1.0), (0.6, 1.7)),
    "human.pedestrian": ((0.2, 1.2), (0.2, 1.2), (0.9, 2.2)),
    "movable_object.barrier": ((0.2, 1.2), (0.3, 3.0), (0.5, 1.5)),
    "movable_object.trafficcone": ((0.2, 0.8), (0.2, 0.8), (0.3, 1.4)),
    "movable_object.pushable_pullable": ((0.3, 2.0), (0.3, 3.0), (0.4, 2.0)),
    "movable_object.debris": ((0.1, 3.0), (0.1, 4.0), (0.1, 2.0)),
    "static_object.bicycle_rack": ((0.4, 3.0), (1.0, 12.0), (0.4, 2.0)),
}
# --- LiDAR theo khoang cach ---
DIST_EDGES = [10, 20, 30, 40, 50]      # bin: 0-10, 10-20, ..., 50+ (m)
MIN_BIN_SAMPLES = 20                   # it nhat n box de tin trung vi cua bin
LOW_FRAC = 0.2                         # thieu < 20% trung vi (cung class, cung khoang cach) => co
MIN_EXPECTED_MEDIAN = 8                # trung vi < 8 diem => bo qua (khong du can cu)
WELL_VISIBLE = ("v60-80", "v80-100", "3", "4")
# --- Chong nhau ---
OVERLAP_WARN_IOU, OVERLAP_ERR_IOU = 0.05, 0.25      # IoU 3D
OVERLAP_WARN_CONTAIN, OVERLAP_ERR_CONTAIN = 0.4, 0.8  # inter / the tich box nho hon
# Cap class chong nhau hop le (tien to ten category): nguoi tren xe dap/xe may, rooc-moc, xe day...
ALLOWED_OVERLAP = [
    ("vehicle.bicycle", "human."), ("vehicle.motorcycle", "human."),
    ("vehicle.trailer", "vehicle.truck"), ("vehicle.trailer", "vehicle.construction"),
    ("vehicle.trailer", "vehicle.car"),
    ("human.", "movable_object.pushable_pullable"),
    # Cum vat can thi cong / hang rao xep sat nhau la binh thuong trong GT
    ("movable_object.", "movable_object."),
    ("movable_object.", "vehicle.construction"),
    ("movable_object.", "human.pedestrian.construction_worker"),
]
HUMAN_PAIR_WARN_IOU = 0.15   # nguoi dung sat nhau trong dam dong: nguong cao hon
# --- Box lech khoi vat the (dung point cloud, can numpy; xem boxfit.py) ---
USE_POINTS = True
FIT_RADIUS, FIT_STEP = 1.5, 0.25   # thu dich box trong +-1.5 m, buoc 0.25 m
FIT_MIN_PTS = 8                    # it hon n diem quanh box thi khong ket luan
FIT_MIN_SHIFT = 0.5                # chi bao khi vi tri tot hon cach >= 0.5 m
FIT_GAIN = 1.5                     # va chua >= 1.5 lan so diem hien tai ...
FIT_MIN_GAIN_PTS = 12              # ... va nhieu hon it nhat 12 diem (sweep: GT 835 -> 429 co, recall gan nhu giu)
FIT_ERR_SHIFT, FIT_ERR_GAIN = 1.0, 2.0   # ERROR neu dich >= 1 m va >= 2 lan + 10 diem
FIT_COMPACT_REL = 1.0              # do gon: so diem trong box / so diem trong box noi rong gap (1 + REL) lan
FIT_MIN_COMPACT = 0.6              # >= nguong nay moi bao (sweep: GT 429 -> 277 co, recall giam 1-10 diem)
# --- Huong nguoc chieu di chuyen ---
MOVING_CLASSES = ("vehicle.car", "vehicle.truck", "vehicle.bus", "vehicle.construction",
                  "vehicle.motorcycle", "vehicle.bicycle")
MIN_SPEED = 1.5            # m/s: cham hon thi khong xac dinh duoc huong di chuyen (xe do)
HEADING_FLIP_DEG = 120     # lech >= 120 do so voi van toc => nguoc chieu (sweep: GT chi co 1 co o 105-150)
HEADING_ERR_SPEED = 3.0    # nhanh hon (m/s) thi ERROR, con lai WARNING
MIN_SAMPLES_FOR_STATS = 50 # >= n mau thi dung phan vi tu du lieu
PCT_LOW, PCT_HIGH = 1, 99    # P1 - P99
PCT_MARGIN = 0.15            # noi 15% khoang [P1,P99] de bot bao nham
HARD_FACTOR = 1.5            # vuot khoang hop ly > 50% => ERROR, con lai WARNING
# ---------------------------------------------------------------------------


def load_table(root, version, name):
    with open(os.path.join(root, version, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def percentile(sorted_vals, p):
    k = (len(sorted_vals) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def min_pts_for(cat):
    return MIN_PTS.get(cat.split(".")[0], DEFAULT_MIN_PTS)


def dist_bin(d):
    for i, edge in enumerate(DIST_EDGES):
        if d < edge:
            return i
    return len(DIST_EDGES)


def bin_label(i):
    lo = DIST_EDGES[i - 1] if i > 0 else 0
    return "%d-%dm" % (lo, DIST_EDGES[i]) if i < len(DIST_EDGES) else "%d+m" % DIST_EDGES[-1]


def load_distances(root, version, anns):
    """Khoang cach 2D (m) tu xe ego den tam moi cuboid. Tra {ann_token: dist}.
    Tra {} neu thieu bang sample_data / ego_pose (vd. du lieu gia lap)."""
    try:
        sample_data = load_table(root, version, "sample_data")
        ego_pose = {e["token"]: e["translation"] for e in load_table(root, version, "ego_pose")}
    except FileNotFoundError:
        return {}
    ego_of_sample = {}
    for sd in sample_data:
        if sd.get("is_key_frame") and "LIDAR_TOP" in sd.get("filename", ""):
            ego_of_sample[sd["sample_token"]] = ego_pose.get(sd["ego_pose_token"])
    dist = {}
    for a in anns:
        e = ego_of_sample.get(a["sample_token"])
        if e:
            t = a["translation"]
            dist[a["token"]] = ((t[0] - e[0]) ** 2 + (t[1] - e[1]) ** 2) ** 0.5
    return dist


def build_pts_expect(anns, cats, dist, vis):
    """Median so diem LiDAR ky vong theo (class, bin khoang cach), tinh tu cac box
    nhin ro (visibility >= 60%). Fallback len nhom class cap 1 (vehicle/human/...)."""
    fine, coarse = defaultdict(list), defaultdict(list)
    for a, cat in zip(anns, cats):
        d, n = dist.get(a["token"]), a.get("num_lidar_pts")
        if d is None or n is None:
            continue
        if str(vis.get(a.get("visibility_token"), "")) not in WELL_VISIBLE:
            continue
        b = dist_bin(d)
        fine[(cat, b)].append(n)
        coarse[(cat.split(".")[0], b)].append(n)

    def med(vals):
        return percentile(sorted(vals), 50)
    expect = {k: (med(v), len(v), "class") for k, v in fine.items() if len(v) >= MIN_BIN_SAMPLES}
    for k, v in coarse.items():
        if len(v) >= MIN_BIN_SAMPLES:
            expect[(k[0] + "*", k[1])] = (med(v), len(v), "nhom")
    return expect


def lookup_expect(expect, cat, b):
    return expect.get((cat, b)) or expect.get((cat.split(".")[0] + "*", b))


def check_lidar(a, cat, dist, vis, expect):
    """Tra (severity, detail) hoac None."""
    n = a.get("num_lidar_pts")
    if n is None:
        return None
    level = str(vis.get(a.get("visibility_token"), ""))
    d = dist.get(a["token"])
    e = lookup_expect(expect, cat, dist_bin(d)) if d is not None else None
    if e is not None:
        med, cnt, src = e
        if med < MIN_EXPECTED_MEDIAN:    # vung nay vat nao cung it diem -> khong the ket luan
            return None
        thr =max(1, int(round(LOW_FRAC * med)))
        where = "d=%.0fm [%s], trung vi %s=%d (n=%d)" % (d, bin_label(dist_bin(d)), src, med, cnt)
    else:   # khong co khoang cach / it mau -> nguong co dinh
        thr = min_pts_for(cat)
        where = "nguong co dinh"
    if n >= thr:
        return None
    if level in ("v0-40", "1"):          # bi che >60%: it diem la binh thuong
        return ("INFO", "num_lidar_pts=%d < %d, bi che nhieu; %s" % (n, thr, where))
    sev = "ERROR" if level in WELL_VISIBLE else "WARNING"
    return (sev, "num_lidar_pts=%d < %d; %s" % (n, thr, where))


def build_size_ranges(rows):
    """rows: list of (cat, w, l, h). Tra {cat: (((lo,hi),)*3, nguon)}."""
    by_cat = defaultdict(list)
    for cat, w, l, h in rows:
        by_cat[cat].append((w, l, h))
    ranges = {}
    for cat, vals in by_cat.items():
        if len(vals) >= MIN_SAMPLES_FOR_STATS:
            dims = []
            for i in range(3):
                col = sorted(v[i] for v in vals)
                lo, hi = percentile(col, PCT_LOW), percentile(col, PCT_HIGH)
                pad = (hi - lo) * PCT_MARGIN
                dims.append((max(lo - pad, 0.0), hi + pad))
            ranges[cat] = (tuple(dims), "data n=%d" % len(vals))
        elif cat in PRIOR_SIZE:
            ranges[cat] = (PRIOR_SIZE[cat], "prior")
    return ranges


def check_size(cat, size, ranges):
    """Tra list (severity, detail). size = (w, l, h)."""
    if cat not in ranges:
        return []
    dims, src = ranges[cat]
    issues = []
    for name, v, (lo, hi) in zip("wlh", size, dims):
        if v < lo or v > hi:
            hard = v < lo / HARD_FACTOR or v > hi * HARD_FACTOR
            issues.append(("ERROR" if hard else "WARNING",
                           "%s=%.2f ngoai [%.2f, %.2f] (%s)" % (name, v, lo, hi, src)))
    return issues


# ---------------------------------------------------------------------------
# Hinh hoc: yaw, da giac BEV, IoU 3D (thuan Python, khong can shapely)
# ---------------------------------------------------------------------------
def yaw_of(rot):
    w, x, y, z = rot
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def bev_corners(a):
    """4 dinh BEV (nguoc chieu kim dong ho). nuScenes size = (w, l, h), l doc theo yaw."""
    cx, cy = a["translation"][0], a["translation"][1]
    w, l = a["size"][0], a["size"][1]
    yaw = yaw_of(a["rotation"])
    c, s = math.cos(yaw), math.sin(yaw)
    pts = []
    for dx, dy in ((l / 2, w / 2), (-l / 2, w / 2), (-l / 2, -w / 2), (l / 2, -w / 2)):
        pts.append((cx + dx * c - dy * s, cy + dx * s + dy * c))
    return pts


def poly_area(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1]
                     for i in range(len(p)))


def clip_poly(subject, clipper):
    """Sutherland-Hodgman: giao 2 da giac loi, ca hai nguoc chieu kim dong ho."""
    out = subject
    for i in range(len(clipper)):
        if not out:
            break
        a, b = clipper[i], clipper[(i + 1) % len(clipper)]

        def inside(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

        def cross(p, q):
            x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
            x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(den) < 1e-12:
                return q
            t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

        inp, out = out, []
        for j in range(len(inp)):
            cur, prv = inp[j], inp[j - 1]
            if inside(cur):
                if not inside(prv):
                    out.append(cross(prv, cur))
                out.append(cur)
            elif inside(prv):
                out.append(cross(prv, cur))
    return out


def overlap_3d(a, b, ca=None, cb=None):
    """Tra (iou3d, inter/vol_nho_hon). ca/cb: dinh BEV da tinh san."""
    ca = ca or bev_corners(a)
    cb = cb or bev_corners(b)
    za0, za1 = a["translation"][2] - a["size"][2] / 2, a["translation"][2] + a["size"][2] / 2
    zb0, zb1 = b["translation"][2] - b["size"][2] / 2, b["translation"][2] + b["size"][2] / 2
    dz = min(za1, zb1) - max(za0, zb0)
    if dz <= 0:
        return 0.0, 0.0
    inter_poly = clip_poly(ca, cb)
    if len(inter_poly) < 3:
        return 0.0, 0.0
    inter = abs(poly_area(inter_poly)) * dz
    va = a["size"][0] * a["size"][1] * a["size"][2]
    vb = b["size"][0] * b["size"][1] * b["size"][2]
    union = va + vb - inter
    return inter / union if union > 0 else 0.0, inter / min(va, vb)


def pair_allowed(c1, c2):
    for g1, g2 in ALLOWED_OVERLAP:
        if (c1.startswith(g1) and c2.startswith(g2)) or (c1.startswith(g2) and c2.startswith(g1)):
            return True
    return False


def check_overlap(anns, cats):
    """Tra list (ann_a, ann_b, cat_a, cat_b, severity, iou, contain)."""
    by_sample = defaultdict(list)
    for a, cat in zip(anns, cats):
        if "translation" not in a or "rotation" not in a:   # du lieu thieu hinh hoc -> bo qua
            continue
        by_sample[a["sample_token"]].append((a, cat))
    res = []
    for items in by_sample.values():
        pre = [(a, cat, bev_corners(a), math.hypot(a["size"][0], a["size"][1]) / 2) for a, cat in items]
        for i in range(len(pre)):
            a, ca, pa, ra = pre[i]
            for j in range(i + 1, len(pre)):
                b, cb, pb, rb = pre[j]
                dx = a["translation"][0] - b["translation"][0]
                dy = a["translation"][1] - b["translation"][1]
                if dx * dx + dy * dy > (ra + rb) ** 2:
                    continue
                iou, cont = overlap_3d(a, b, pa, pb)
                if iou < OVERLAP_WARN_IOU and cont < OVERLAP_WARN_CONTAIN:
                    continue
                if ca.startswith("human.") and cb.startswith("human.") and iou < HUMAN_PAIR_WARN_IOU:
                    continue
                if pair_allowed(ca, cb):
                    continue
                sev = "ERROR" if (iou >= OVERLAP_ERR_IOU or cont >= OVERLAP_ERR_CONTAIN) else "WARNING"
                res.append((a, b, ca, cb, sev, iou, cont))
    return res


def angle_diff(a, b):
    d = (a - b + math.pi) % (2 * math.pi) - math.pi
    return abs(d)


def check_heading(anns, cats, sample_ts):
    """Huong cuboid nguoc chieu di chuyen. Van toc tu prev/next cung instance (toa do global)."""
    by_tok = {a["token"]: a for a in anns}
    res = []
    for a, cat in zip(anns, cats):
        if not any(cat.startswith(p) for p in MOVING_CLASSES) or "translation" not in a:
            continue
        p = by_tok.get(a.get("prev")) or a
        n = by_tok.get(a.get("next")) or a
        if p is n:
            continue
        t0, t1 = sample_ts.get(p["sample_token"]), sample_ts.get(n["sample_token"])
        if t0 is None or t1 is None or t1 <= t0:
            continue
        dt = (t1 - t0) / 1e6
        vx = (n["translation"][0] - p["translation"][0]) / dt
        vy = (n["translation"][1] - p["translation"][1]) / dt
        speed = math.hypot(vx, vy)
        if speed < MIN_SPEED:
            continue
        diff = angle_diff(yaw_of(a["rotation"]), math.atan2(vy, vx))
        if diff >= math.radians(HEADING_FLIP_DEG):
            sev = "ERROR" if speed >= HEADING_ERR_SPEED else "WARNING"
            res.append((a, cat, sev, math.degrees(diff), speed, math.atan2(vy, vx)))
    return res


def analyze(anns, cats, vis, dist=None, sample_ts=None, ranges=None, expect=None,
            anns_motion=None, points_fn=None):
    """Loi QC chay tren du lieu trong bo nho (dung chung cho nuScenes va CVAT).

    anns/cats      : annotation dang nuScenes (token, sample_token, translation, size=(w,l,h), rotation, ...)
                     o he toa do bat ky (mien la cung he voi point cloud do points_fn tra ve).
    vis            : {visibility_token: level}
    dist           : {ann_token: khoang cach toi xe}; rong -> nguong LiDAR co dinh
    sample_ts      : {sample_token: timestamp us} cho kiem tra huong
    ranges/expect  : bang tham chieu kich thuoc / so diem; None -> tinh tu chinh du lieu
    anns_motion    : cung danh sach annotation (cung thu tu, cung token) nhung o toa do GLOBAL, dung de tinh
                     van toc; None -> dung anns
    points_fn      : f(sample_token) -> mang Nx3 numpy cung he toa do voi anns, hoac None; None -> bo BOX_OFFSET
    Tra (rows, ctx).
    """
    dist = dist or {}
    sample_ts = sample_ts or {}
    if ranges is None:
        ranges = build_size_ranges(
            [(c, a["size"][0], a["size"][1], a["size"][2]) for c, a in zip(cats, anns)])
    if expect is None:
        expect = build_pts_expect(anns, cats, dist, vis) if dist else {}

    rows = []
    for a, cat in zip(anns, cats):
        res = check_lidar(a, cat, dist, vis, expect)
        if res:
            rows.append((a["sample_token"], a["token"], cat, "LOW_LIDAR_PTS", res[0], res[1]))
        for sev, detail in check_size(cat, a["size"], ranges):
            rows.append((a["sample_token"], a["token"], cat, "BAD_SIZE", sev, detail))

    # --- Chong nhau: moi cap sinh 2 dong (mot cho moi box) ---
    overlaps = check_overlap(anns, cats)
    for a, b, ca, cb, sev, iou, cont in overlaps:
        for x, y, cx in ((a, b, ca), (b, a, cb)):
            rows.append((x["sample_token"], x["token"], cx, "OVERLAP", sev,
                         "IoU3D=%.2f, chua=%.0f%% voi %s (%s)" % (iou, 100 * cont, y["token"][:8],
                                                                  cb if x is a else ca)))

    # --- Huong nguoc chieu di chuyen ---
    headings = check_heading(anns_motion or anns, cats, sample_ts)
    for a, cat, sev, diff, speed, _vel_yaw in headings:
        rows.append((a["sample_token"], a["token"], cat, "HEADING_REVERSED", sev,
                     "yaw lech %.0f do so voi van toc, toc do %.1f m/s" % (diff, speed)))

    # --- Box lech khoi vat the (dung point cloud that) ---
    offsets = {}
    if points_fn is not None:
        from cuboidqc.core import boxfit as boxfit
        fit_rows, offsets = boxfit.run_checks(points_fn, anns, cats)
        rows += fit_rows

    ctx = dict(anns=anns, cats=cats, ranges=ranges, expect=expect, overlaps=overlaps, headings=headings,
               dist=dist, vis=vis, offsets=offsets)
    return rows, ctx


def run(root, version, out_path, quiet=False, ctx_out=None, points_root=None, use_points=None):
    categories = {c["token"]: c["name"] for c in load_table(root, version, "category")}
    instances = {i["token"]: categories.get(i["category_token"], "unknown")
                 for i in load_table(root, version, "instance")}
    anns = load_table(root, version, "sample_annotation")
    try:
        vis = {v["token"]: v.get("level", v["token"])
               for v in load_table(root, version, "visibility")}
    except FileNotFoundError:
        vis = {}

    cats = [instances.get(a["instance_token"], "unknown") for a in anns]
    dist = load_distances(root, version, anns)
    if not quiet:
        print("Khoang cach ego: %s" % ("co (%d box)" % len(dist) if dist else "KHONG co -> dung nguong co dinh"))
    try:
        sample_ts = {s["token"]: s["timestamp"] for s in load_table(root, version, "sample")}
    except FileNotFoundError:
        sample_ts = {}

    points_fn = None
    if USE_POINTS if use_points is None else use_points:
        try:
            from cuboidqc.core import boxfit as boxfit
            from cuboidqc.core import lidar as lidar
            lid = lidar.get_lidar(points_root or root, version)
            points_fn = lid.points_np
        except ImportError:
            if not quiet:
                print("Bo qua BOX_OFFSET: can numpy (pip install numpy)")
        except (FileNotFoundError, KeyError):
            if not quiet:
                print("Bo qua BOX_OFFSET: thieu sample_data/point cloud trong %s" % (points_root or root))

    rows, ctx = analyze(anns, cats, vis, dist=dist, sample_ts=sample_ts, points_fn=points_fn)

    sev_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    rows.sort(key=lambda r: (sev_order[r[4]], r[3], r[2]))
    with open(paths.ensure_parent(out_path), "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["sample_token", "annotation_token", "category", "issue", "severity", "detail"])
        wr.writerows(rows)

    if not quiet:
        flagged = len({r[1] for r in rows if r[4] != "INFO"})   # INFO = bi che, khong tinh la loi
        print("Tong so cuboid : %d" % len(anns))
        print("Cuboid bi co   : %d (%.1f%%)" % (flagged, 100.0 * flagged / max(len(anns), 1)))
        for (issue, sev), c in sorted(Counter((r[3], r[4]) for r in rows).items()):
            print("  %-14s %-8s %d" % (issue, sev, c))
        print("Bao cao        : %s" % out_path)
    if ctx_out is not None:   # du lieu trung gian cho fixes.py / viewer.py
        ctx_out.update(ctx)
    return rows


# ---------------------------------------------------------------------------
# Cau hinh: ghi/doc cac tham so chinh sua duoc qua file JSON
# ---------------------------------------------------------------------------
CONFIG_KEYS = [
    "MIN_PTS", "DEFAULT_MIN_PTS", "DIST_EDGES", "MIN_BIN_SAMPLES", "LOW_FRAC",
    "MIN_EXPECTED_MEDIAN", "WELL_VISIBLE",
    "MIN_SAMPLES_FOR_STATS", "PCT_LOW", "PCT_HIGH", "PCT_MARGIN", "HARD_FACTOR", "PRIOR_SIZE",
    "OVERLAP_WARN_IOU", "OVERLAP_ERR_IOU", "OVERLAP_WARN_CONTAIN", "OVERLAP_ERR_CONTAIN",
    "HUMAN_PAIR_WARN_IOU", "ALLOWED_OVERLAP",
    "MOVING_CLASSES", "MIN_SPEED", "HEADING_FLIP_DEG", "HEADING_ERR_SPEED",
    "USE_POINTS", "FIT_RADIUS", "FIT_STEP", "FIT_MIN_PTS", "FIT_MIN_SHIFT", "FIT_GAIN",
    "FIT_MIN_GAIN_PTS", "FIT_ERR_SHIFT", "FIT_ERR_GAIN", "FIT_COMPACT_REL", "FIT_MIN_COMPACT",
]


def dump_config(path):
    cfg = {k: globals()[k] for k in CONFIG_KEYS}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1, ensure_ascii=False)


def apply_config(path):
    """Ghi de cac tham so mac dinh bang gia tri trong file JSON (chi cac khoa trong CONFIG_KEYS)."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    unknown = [k for k in cfg if k not in CONFIG_KEYS]
    if unknown:
        raise SystemExit("Khoa cau hinh khong hop le: %s" % ", ".join(unknown))
    for k, v in cfg.items():
        if k == "PRIOR_SIZE":
            v = {c: tuple(tuple(x) for x in dims) for c, dims in v.items()}
        elif k == "ALLOWED_OVERLAP":
            v = [tuple(p) for p in v]
        elif k in ("WELL_VISIBLE", "MOVING_CLASSES"):
            v = tuple(v)
        globals()[k] = v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataroot")
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--out", default=str(paths.DATA / "report.csv"))
    ap.add_argument("--config", help="file JSON ghi de nguong (xem --dump-config)")
    ap.add_argument("--dump-config", metavar="FILE", help="ghi nguong mac dinh ra FILE roi thoat")
    ap.add_argument("--no-points", action="store_true", help="khong doc point cloud (bo checker BOX_OFFSET)")
    args = ap.parse_args()
    if args.dump_config:
        dump_config(args.dump_config)
        print("Da ghi cau hinh mac dinh: %s" % args.dump_config)
        return
    if not args.dataroot:
        ap.error("can --dataroot")
    if args.config:
        apply_config(args.config)
    run(args.dataroot, args.version, args.out, use_points=False if args.no_points else None)


if __name__ == "__main__":
    main()

"""Goi y sua tu dong cho cac co cua qc.py.

Moi goi y la dict:
  kind   : resize | flip_yaw | align_yaw | refit | delete | review
  text   : mo ta bang tieng Viet cho annotator
  box    : box de xuat {translation, size, yaw} (None neu chi la hanh dong)
  delete : annotation token nen xoa (chi voi kind == delete)
"""
import math
from collections import defaultdict

from cuboidqc.core import lidar as lidar
from cuboidqc.core import qc as qc

REFIT_RADIUS = 1.5      # m: tim vi tri day diem nhat trong +-1.5 m
REFIT_STEP = 0.1
REFIT_MIN_PTS = 8       # it hon thi khong du can cu de dich box
REFIT_GAIN = 1.3        # so diem moi phai nhieu hon >= 1.3 lan va +5 diem
DUP_IOU, DUP_CONTAIN = 0.5, 0.8


def box_of(a, yaw=None):
    return {"translation": list(a["translation"]), "size": list(a["size"]),
            "yaw": qc.yaw_of(a["rotation"]) if yaw is None else yaw}


def class_medians(anns, cats):
    by = defaultdict(list)
    for a, c in zip(anns, cats):
        by[c].append(a["size"])
    med = {}
    for c, vals in by.items():
        if len(vals) >= qc.MIN_SAMPLES_FOR_STATS:
            med[c] = [qc.percentile(sorted(v[i] for v in vals), 50) for i in range(3)]
        elif c in qc.PRIOR_SIZE:
            med[c] = [(lo + hi) / 2 for lo, hi in qc.PRIOR_SIZE[c]]
    return med


def fix_size(a, cat, ranges, medians):
    if cat not in ranges or cat not in medians:
        return None
    dims, _src = ranges[cat]
    size = list(a["size"])
    changed = []
    for i, name in enumerate("wlh"):
        lo, hi = dims[i]
        if size[i] < lo or size[i] > hi:
            changed.append("%s %.2f -> %.2f" % (name, size[i], medians[cat][i]))
            size[i] = medians[cat][i]
    if not changed:
        return None
    b = box_of(a)
    b["size"] = size
    return {"kind": "resize", "basis": "class", "box": b,
            "text": "Dua kich thuoc ve trung vi cua class: " + ", ".join(changed) + " (m)"}


def fix_size_by_track(a, others, min_others=3, tol=0.10, min_consistent=0.8):
    """Sua kich thuoc theo trung vi cua CHINH track (cac frame khac cua cung vat the).

    Kich thuoc mot vat khong doi qua cac frame, nen trung vi cua track dang tin hon trung vi ca class
    (khong bi sua do cho cac chieu khac). Chi dung khi track co >= min_others frame khac va da so (>= 80%)
    nhat quan trong +-tol; khong thi tra None (de dung goi y theo class)."""
    if len(others) < min_others:
        return None
    med = [qc.percentile(sorted(o["size"][i] for o in others), 50) for i in range(3)]
    inliers = [o for o in others if all(abs(o["size"][i] - med[i]) <= tol * med[i] for i in range(3))]
    if len(inliers) < min_consistent * len(others):
        return None
    med = [qc.percentile(sorted(o["size"][i] for o in inliers), 50) for i in range(3)]
    if all(abs(a["size"][i] - med[i]) <= 0.02 * med[i] for i in range(3)):
        return None
    b = box_of(a)
    b["size"] = med
    return {"kind": "resize", "basis": "track", "box": b,
            "text": "Dua kich thuoc ve trung vi cua track (%d frame khac): %s (m)" %
                    (len(inliers), " x ".join("%.2f" % x for x in (med[1], med[0], med[2])))}


def fix_heading(a, diff_deg, vel_yaw):
    yaw = qc.yaw_of(a["rotation"])
    if abs(diff_deg - 180) <= 30:
        return {"kind": "flip_yaw", "box": box_of(a, yaw + math.pi),
                "text": "Lat huong 180 do (yaw lech %.0f do so voi huong di chuyen)" % diff_deg}
    return {"kind": "align_yaw", "box": box_of(a, vel_yaw),
            "text": "Can theo huong di chuyen (yaw lech %.0f do)" % diff_deg}


def fix_overlap(a, b, cat_a, cat_b, iou, cont):
    """Goi y cho box `a` trong cap (a, b)."""
    if cat_a == cat_b and iou >= DUP_IOU and cont >= DUP_CONTAIN:
        na, nb = a.get("num_lidar_pts") or 0, b.get("num_lidar_pts") or 0
        victim = a if (na, a["token"]) <= (nb, b["token"]) else b
        if victim is a:
            return {"kind": "delete", "delete": a["token"], "box": None,
                    "text": "Co ve la box trung (IoU %.2f). Giu box nhieu diem hon, xoa box nay" % iou}
        return {"kind": "review", "box": None,
                "text": "Co ve la box trung (IoU %.2f). Nen xoa box kia (%s), giu box nay" % (iou, b["token"][:8])}
    return {"kind": "review", "box": None,
            "text": "Hai box chong nhau (IoU %.2f, chua %.0f%%). Tach box ra hoac xoa neu thua" % (iou, 100 * cont)}


def refit_box(a, pts):
    """Dich box (giu nguyen size, yaw) toi vi tri chua nhieu diem LiDAR nhat trong +-REFIT_RADIUS."""
    b = box_of(a)
    cx, cy, cz = b["translation"]
    w, l, h = b["size"]
    yaw = b["yaw"]
    c, s = math.cos(yaw), math.sin(yaw)
    r = REFIT_RADIUS + math.hypot(w, l) / 2 + 0.5
    # lay diem trong vung tim kiem, bo diem mat dat (thap hon day box 0.15 m)
    near = []
    for p in pts:
        if abs(p[0] - cx) <= r and abs(p[1] - cy) <= r and cz - h / 2 + 0.15 <= p[2] <= cz + h / 2:
            dx, dy = p[0] - cx, p[1] - cy
            near.append((dx * c + dy * s, -dx * s + dy * c))   # (u, v) trong khung box
    if len(near) < REFIT_MIN_PTS:
        return None, len(near), 0
    steps = int(REFIT_RADIUS / REFIT_STEP)
    cur = sum(1 for u, v in near if abs(u) <= l / 2 and abs(v) <= w / 2)
    best, best_du, best_dv = cur, 0.0, 0.0
    for i in range(-steps, steps + 1):
        du = i * REFIT_STEP
        for j in range(-steps, steps + 1):
            dv = j * REFIT_STEP
            n = sum(1 for u, v in near if abs(u - du) <= l / 2 and abs(v - dv) <= w / 2)
            if n > best or (n == best and n > 0 and math.hypot(du, dv) < math.hypot(best_du, best_dv)):
                best, best_du, best_dv = n, du, dv
    if best < cur * REFIT_GAIN or best - cur < 5:
        return None, cur, best
    nb = dict(b)
    nb["translation"] = [cx + best_du * c - best_dv * s, cy + best_du * s + best_dv * c, cz]
    return nb, cur, best


def fix_lidar(a, pts):
    if pts is None:
        return {"kind": "review", "box": None,
                "text": "It diem LiDAR: kiem tra box co dung vat the khong (khong co point cloud de tu dong dich box)"}
    nb, cur, best = refit_box(a, pts)
    if nb:
        shift = math.hypot(nb["translation"][0] - a["translation"][0], nb["translation"][1] - a["translation"][1])
        return {"kind": "refit", "box": nb,
                "text": "Dich box %.1f m toi cho day diem hon: %d -> %d diem" % (shift, cur, best)}
    if cur == 0 and best == 0:
        return {"kind": "review", "box": None,
                "text": "Khong co diem nao quanh box (+-%.1f m): co the la box ma, can xoa hoac xac minh" % REFIT_RADIUS}
    return {"kind": "review", "box": None,
            "text": "It diem nhung dich box khong cai thien them: kiem tra thu cong (vat bi che / xa?)"}


def build_suggestions(ctx, lid=None, medians=None):
    """Tra {(annotation_token, issue): fix}. ctx lay tu qc.run(..., ctx_out=ctx).
    medians: {category: [w, l, h]} tham chieu (vd. tu profile); None -> tinh tu chinh du lieu."""
    anns, cats = ctx["anns"], ctx["cats"]
    medians = medians if medians is not None else class_medians(anns, cats)
    out = {}
    for a, cat in zip(anns, cats):
        f = fix_size(a, cat, ctx["ranges"], medians)
        if f:
            out[(a["token"], "BAD_SIZE")] = f
    for a, cat, _sev, diff, _speed, vel_yaw in ctx["headings"]:
        out[(a["token"], "HEADING_REVERSED")] = fix_heading(a, diff, vel_yaw)
    for a, b, ca, cb, _sev, iou, cont in ctx["overlaps"]:
        out[(a["token"], "OVERLAP")] = fix_overlap(a, b, ca, cb, iou, cont)
        out[(b["token"], "OVERLAP")] = fix_overlap(b, a, cb, ca, iou, cont)
    for tok, res in ctx.get("offsets", {}).items():
        out[(tok, "BOX_OFFSET")] = {
            "kind": "refit", "box": res["box"],
            "text": "Dich box %.1f m (giu nguyen size/yaw): %d -> %d diem LiDAR" % (res["shift"], res["cur"], res["best"])}
    return out


def add_lidar_suggestions(ctx, rows, out, lid):
    """Bo sung goi y cho LOW_LIDAR_PTS (can point cloud)."""
    by_tok = {a["token"]: a for a in ctx["anns"]}
    for r in rows:
        if r[3] != "LOW_LIDAR_PTS" or r[4] == "INFO":
            continue
        a = by_tok[r[1]]
        out[(a["token"], "LOW_LIDAR_PTS")] = fix_lidar(a, lid.points_global(a["sample_token"]) if lid else None)
    return out


def apply_fix(a, fix):
    """Ap goi y len ban sao cua annotation `a`; tra annotation moi (None neu bi xoa)."""
    if fix.get("kind") == "delete":
        return None
    if not fix.get("box"):
        return a
    b = dict(a)
    b["translation"] = list(fix["box"]["translation"])
    b["size"] = list(fix["box"]["size"])
    yaw = fix["box"]["yaw"]
    b["rotation"] = [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]
    return b

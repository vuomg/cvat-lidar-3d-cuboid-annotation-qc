"""Checker BOX_OFFSET: box lech khoi vat the, dua tren hinh hoc diem LiDAR that (can numpy).

Y tuong: giu nguyen size va yaw cua box, thu dich box trong +-FIT_RADIUS (luoi FIT_STEP). Neu co vi tri chua
nhieu diem hon han vi tri hien tai thi box dang lech. Khong dung num_lidar_pts co san, nen bat duoc ca
box lech nhung van con du diem (checker LOW_LIDAR_PTS bo sot).
"""
import math
from collections import defaultdict

from cuboidqc.core import lidar as lidar
from cuboidqc.core import qc as qc

try:
    import numpy as np
except ImportError:
    np = None

GROUND_CLEAR = 0.15      # bo diem thap hon day box < 0.15 m (mat dat)


def owner_map(boxes, P):
    """owner[i] = chi so box chua diem i (-1 neu khong thuoc box nao). boxes: list annotation."""
    owner = np.full(len(P), -1, dtype=np.int32)
    for i, a in enumerate(boxes):
        cx, cy, cz = a["translation"]
        w, l, h = a["size"]
        R = math.hypot(w, l) / 2
        win = np.nonzero((np.abs(P[:, 0] - cx) <= R) & (np.abs(P[:, 1] - cy) <= R))[0]
        if not len(win):
            continue
        yaw = qc.yaw_of(a["rotation"])
        c, s = math.cos(yaw), math.sin(yaw)
        dx, dy, dz = P[win, 0] - cx, P[win, 1] - cy, P[win, 2] - cz
        inside = ((np.abs(dx * c + dy * s) <= l / 2) & (np.abs(-dx * s + dy * c) <= w / 2)
                  & (np.abs(dz) <= h / 2))
        owner[win[inside]] = i
    return owner


def fit_box(a, P, owner=None, idx=None):
    """Tra dict(cur, best, shift, box) hoac None neu qua it diem. P: Nx3 toa do global.
    owner/idx: bo qua diem da thuoc ve box KHAC (tranh dem nham diem cua vat the ke ben)."""
    cx, cy, cz = a["translation"]
    w, l, h = a["size"]
    yaw = qc.yaw_of(a["rotation"])
    r = qc.FIT_RADIUS + math.hypot(w, l) / 2 + 0.3
    m = ((np.abs(P[:, 0] - cx) <= r) & (np.abs(P[:, 1] - cy) <= r)
         & (P[:, 2] >= cz - h / 2 + GROUND_CLEAR) & (P[:, 2] <= cz + h / 2))
    if owner is not None:
        m &= (owner == -1) | (owner == idx)
    Q = P[m]
    if len(Q) < qc.FIT_MIN_PTS:
        return None
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dy = Q[:, 0] - cx, Q[:, 1] - cy
    u, v = dx * c + dy * s, -dx * s + dy * c
    n = int(round(qc.FIT_RADIUS / qc.FIT_STEP))
    offs = np.arange(-n, n + 1) * qc.FIT_STEP
    U = (np.abs(u[:, None] - offs[None, :]) <= l / 2).astype(np.int32)    # m x G
    V = (np.abs(v[:, None] - offs[None, :]) <= w / 2).astype(np.int32)
    counts = U.T @ V                                                       # G x G, [du, dv]
    cur = int(counts[n, n])
    best = int(counts.max())
    iu, iv = np.nonzero(counts == best)
    dist = np.hypot(offs[iu], offs[iv])
    k = int(np.argmin(dist))
    du, dv = float(offs[iu[k]]), float(offs[iv[k]])
    # Do gon: ty le diem nam trong box o vi tri tot nhat so voi box do noi rong theo ty le kich thuoc
    # (FIT_COMPACT_REL = 1.0 nghia la gap doi). Vat the that gon (~1); tuong / le duong keo dai ra
    # ngoai box nen thap.
    k_ = 1.0 + qc.FIT_COMPACT_REL
    big = int(((np.abs(u - du) <= l / 2 * k_) & (np.abs(v - dv) <= w / 2 * k_)).sum())
    return {"cur": cur, "best": best, "shift": float(dist[k]), "compact": best / max(big, 1),
            "box": {"translation": [cx + du * c - dv * s, cy + du * s + dv * c, cz],
                    "size": [w, l, h], "yaw": yaw}}


def count_in_box(P, a):
    """So diem trong box (tinh lai num_lidar_pts khi box bi dich/doi)."""
    cx, cy, cz = a["translation"]
    w, l, h = a["size"]
    yaw = qc.yaw_of(a["rotation"])
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dy, dz = P[:, 0] - cx, P[:, 1] - cy, P[:, 2] - cz
    return int(((np.abs(dx * c + dy * s) <= l / 2) & (np.abs(-dx * s + dy * c) <= w / 2)
                & (np.abs(dz) <= h / 2)).sum())


def judge(res):
    """Tra severity hoac None."""
    if not res or res["shift"] < qc.FIT_MIN_SHIFT:
        return None
    cur, best = res["cur"], res["best"]
    if best < cur * qc.FIT_GAIN or best - cur < qc.FIT_MIN_GAIN_PTS:
        return None
    if res["compact"] < qc.FIT_MIN_COMPACT:     # diem keo dai ra ngoai box: tuong / le duong, khong phai vat the
        return None
    if res["shift"] >= qc.FIT_ERR_SHIFT and best >= qc.FIT_ERR_GAIN * cur + 10:
        return "ERROR"
    return "WARNING"


def run_checks(points_fn, anns, cats):
    """Tra (rows, offsets). rows cung dinh dang voi qc.run; offsets = {annotation_token: ket qua fit}.
    points_fn(sample_token) -> Nx3 numpy (cung he toa do voi anns) hoac None."""
    if np is None:
        raise ImportError("numpy")
    by_sample = defaultdict(list)
    for a, cat in zip(anns, cats):
        if "translation" in a and "rotation" in a:
            by_sample[a["sample_token"]].append((a, cat))
    rows, offsets = [], {}
    for sample, items in by_sample.items():
        P = points_fn(sample)
        if P is None:
            continue
        owner = owner_map([a for a, _ in items], P)
        for i, (a, cat) in enumerate(items):
            res = fit_box(a, P, owner, i)
            sev = judge(res)
            if sev:
                rows.append((sample, a["token"], cat, "BOX_OFFSET", sev,
                             "dich ~%.1f m se chua %d diem thay vi %d (giu nguyen size/yaw)" %
                             (res["shift"], res["best"], res["cur"])))
                offsets[a["token"]] = res
    return rows, offsets

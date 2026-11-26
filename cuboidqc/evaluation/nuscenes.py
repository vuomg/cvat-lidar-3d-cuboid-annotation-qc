#!/usr/bin/env python3
"""Danh gia 4 checker cua qc.py bang cach chen loi nhieu muc nang/nhe vao ban sao nuScenes that.

Voi moi loai loi: chen N box loi cho moi muc, chay qc, do
  - recall theo muc (bat duoc >= WARNING; va rieng ERROR)
  - precision can duoi: TP / (TP + moi box bi co ma khong phai box chen vao)
    (co GT nuScenes bi co cung tinh la FP -> day la can DUOI, vi GT co the that su co loi)

Han che: lidar duoc mo phong bang cach giam num_lidar_pts (khong tinh lai diem tu point cloud).

  python -m cuboidqc.evaluation.nuscenes --dataroot V:\\data\\nuscenes --version v1.0-mini [--config config.json]
"""
import argparse
import copy
import json
import math
import os
import random
import shutil
import tempfile
from collections import defaultdict
from cuboidqc import paths

from cuboidqc.core import qc as qc

TABLES = ["category", "instance", "visibility", "sample", "sample_data", "ego_pose"]
N_PER_LEVEL = 50

LIDAR_LEVELS = [("giu 50% diem", 0.5), ("giu 25% diem", 0.25), ("giu 10% diem", 0.1), ("0 diem", 0.0)]
SIZE_LEVELS = [("x1.15", 1.15), ("x1.3", 1.3), ("x1.6", 1.6), ("x2.0", 2.0), ("x0.7", 0.7), ("x0.5", 0.5)]
OVERLAP_LEVELS = [("dich 0.1 chieu dai", 0.1), ("dich 0.3", 0.3), ("dich 0.5", 0.5), ("dich 0.8", 0.8)]
OFFSET_LEVELS = [("dich 0.5 m", 0.5), ("dich 0.8 m", 0.8), ("dich 1.2 m", 1.2), ("dich 1.8 m", 1.8)]
HEADING_LEVELS = [("lat 180 do", 180), ("lech 165", 165), ("lech 150", 150),
                  ("lech 135", 135), ("lech 120", 120), ("lech 90", 90)]


class Ctx:
    def __init__(self, root, version):
        self.root, self.version = root, version
        self.anns = qc.load_table(root, version, "sample_annotation")
        inst = {i["token"]: i["category_token"] for i in qc.load_table(root, version, "instance")}
        catn = {c["token"]: c["name"] for c in qc.load_table(root, version, "category")}
        self.cat = {a["token"]: catn[inst[a["instance_token"]]] for a in self.anns}
        self.vis = {v["token"]: v["level"] for v in qc.load_table(root, version, "visibility")}
        self.ts = {s["token"]: s["timestamp"] for s in qc.load_table(root, version, "sample")}
        self.by_tok = {a["token"]: a for a in self.anns}
        self.dist = qc.load_distances(root, version, self.anns)
        from cuboidqc.core import lidar as lidar
        self.lid = lidar.get_lidar(root, version)
        self.tmp = tempfile.mkdtemp(prefix="qc_eval_")
        vdir = os.path.join(self.tmp, version)
        os.makedirs(vdir)
        for t in TABLES:
            shutil.copy(os.path.join(root, version, t + ".json"), vdir)

    def speed(self, a):
        p, n = self.by_tok.get(a.get("prev")), self.by_tok.get(a.get("next"))
        if not p or not n:
            return 0.0
        dt = (self.ts[n["sample_token"]] - self.ts[p["sample_token"]]) / 1e6
        if dt <= 0:
            return 0.0
        return math.hypot(n["translation"][0] - p["translation"][0],
                          n["translation"][1] - p["translation"][1]) / dt

    def run(self, anns, ctx_out=None):
        path = os.path.join(self.tmp, self.version, "sample_annotation.json")
        with open(path, "w") as f:
            json.dump(anns, f)
        return qc.run(self.tmp, self.version, os.path.join(self.tmp, "r.csv"), quiet=True, ctx_out=ctx_out,
                      points_root=self.root)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def flagged(rows, issue, sev=("ERROR", "WARNING")):
    return {r[1] for r in rows if r[3] == issue and r[4] in sev}


def pick(rng, pool, n_levels):
    """Chon n_levels nhom, moi nhom N_PER_LEVEL box, khong trung nhau."""
    need = N_PER_LEVEL * n_levels
    if len(pool) < need:
        raise SystemExit("Khong du box de chen loi (can %d, co %d)" % (need, len(pool)))
    chosen = rng.sample(pool, need)
    return [chosen[i * N_PER_LEVEL:(i + 1) * N_PER_LEVEL] for i in range(n_levels)]


def set_yaw(a, yaw):
    a["rotation"] = [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]


def make_injection(ctx, issue, rng):
    """Tra (anns_moi, {nhan_muc: set(token chen)}, set(token duoc tinh la 'chen' khi do precision))."""
    anns = copy.deepcopy(ctx.anns)
    by = {a["token"]: a for a in anns}
    groups = {}
    allowed = set()
    if issue == "LOW_LIDAR_PTS":
        pool = [a["token"] for a in anns
                if ctx.vis.get(a.get("visibility_token")) in ("v60-80", "v80-100")
                and (a.get("num_lidar_pts") or 0) >= 30
                and ctx.cat[a["token"]].startswith(("vehicle.car", "vehicle.truck", "human.pedestrian"))]
        for (label, frac), toks in zip(LIDAR_LEVELS, pick(rng, pool, len(LIDAR_LEVELS))):
            for t in toks:
                by[t]["num_lidar_pts"] = int(by[t]["num_lidar_pts"] * frac)
            groups[label] = set(toks)
    elif issue == "BAD_SIZE":
        pool = [a["token"] for a in anns if ctx.cat[a["token"]] in ("vehicle.car", "human.pedestrian.adult")]
        for (label, f), toks in zip(SIZE_LEVELS, pick(rng, pool, len(SIZE_LEVELS))):
            for t in toks:
                by[t]["size"] = [x * f for x in by[t]["size"]]
            groups[label] = set(toks)
    elif issue == "OVERLAP":
        pool = [a["token"] for a in anns if ctx.cat[a["token"]] == "vehicle.car" and a["size"][1] > 3]
        dups = []
        k = 0
        for (label, frac), toks in zip(OVERLAP_LEVELS, pick(rng, pool, len(OVERLAP_LEVELS))):
            g = set()
            for t in toks:
                a = by[t]
                yaw = qc.yaw_of(a["rotation"])
                d = copy.deepcopy(a)
                d["token"] = "DUP%05d" % k
                k += 1
                d["translation"] = [a["translation"][0] + math.cos(yaw) * a["size"][1] * frac,
                                    a["translation"][1] + math.sin(yaw) * a["size"][1] * frac,
                                    a["translation"][2]]
                d["prev"] = d["next"] = ""
                dups.append(d)
                g.add(d["token"])
                g.add(t)      # pho nhan ban sao cung duoc coi la dung (ca cap bi co)
            groups[label] = g
        anns = anns + dups
    elif issue == "BOX_OFFSET":
        from cuboidqc.core import boxfit as boxfit
        pool = [a["token"] for a in anns if ctx.lid.available(a["sample_token"])
                and ((ctx.cat[a["token"]] == "vehicle.car" and (a.get("num_lidar_pts") or 0) >= 40)
                     or (ctx.cat[a["token"]] == "human.pedestrian.adult" and (a.get("num_lidar_pts") or 0) >= 15))]
        for (label, dist), toks in zip(OFFSET_LEVELS, pick(rng, pool, len(OFFSET_LEVELS))):
            for t in toks:
                ang = rng.uniform(0, 2 * math.pi)
                by[t]["translation"] = [by[t]["translation"][0] + dist * math.cos(ang),
                                        by[t]["translation"][1] + dist * math.sin(ang), by[t]["translation"][2]]
                # num_lidar_pts duoc he thong tinh lai theo box moi (nhu cong cu gan nhan that)
                by[t]["num_lidar_pts"] = boxfit.count_in_box(ctx.lid.points_np(by[t]["sample_token"]), by[t])
            groups[label] = set(toks)
    elif issue == "HEADING_REVERSED":
        pool = [a["token"] for a in anns
                if ctx.cat[a["token"]] == "vehicle.car" and ctx.speed(a) >= 3.5]
        for (label, deg), toks in zip(HEADING_LEVELS, pick(rng, pool, len(HEADING_LEVELS))):
            for t in toks:
                set_yaw(by[t], qc.yaw_of(by[t]["rotation"]) + math.radians(deg))
            groups[label] = set(toks)
    for g in groups.values():
        allowed |= g
    return anns, groups, allowed


ALL_ISSUES = ("LOW_LIDAR_PTS", "BAD_SIZE", "OVERLAP", "HEADING_REVERSED", "BOX_OFFSET")


def evaluate(ctx, seeds, issues=ALL_ISSUES):
    saved = qc.USE_POINTS
    out = {}
    try:
        qc.USE_POINTS = "BOX_OFFSET" in issues
        clean_rows = ctx.run(ctx.anns)
        for issue in issues:
            qc.USE_POINTS = saved and issue == "BOX_OFFSET"      # chi checker BOX_OFFSET can point cloud
            levels = defaultdict(lambda: [0, 0, 0, 0])   # label -> [tong, >=WARNING, ERROR, BOX_OFFSET hoac LOW_LIDAR]
            tp = fp = 0
            clean_flags = len(flagged(clean_rows, issue))
            for seed in range(seeds):
                rng = random.Random(seed)
                anns, groups, allowed = make_injection(ctx, issue, rng)
                rows = ctx.run(anns)
                got_any, got_err = flagged(rows, issue), flagged(rows, issue, ("ERROR",))
                got_union = got_any | flagged(rows, "LOW_LIDAR_PTS")
                for label, toks in groups.items():
                    # OVERLAP: moi nhom chua ca ban sao lan ban goc -> chi tinh ban sao (DUP*)
                    core = {t for t in toks if t.startswith("DUP")} if issue == "OVERLAP" else toks
                    levels[label][0] += len(core)
                    levels[label][1] += len(core & got_any)
                    levels[label][2] += len(core & got_err)
                    levels[label][3] += len(core & got_union)
                tp += len(got_any & allowed)
                fp += len(got_any - allowed)
            out[issue] = {"levels": dict(levels), "tp": tp, "fp": fp, "clean_flags": clean_flags}
    finally:
        qc.USE_POINTS = saved
    return out


def render(res, seeds, n_boxes):
    lines = ["# Bao cao danh gia qc.py", "",
             "- Du lieu: %d cuboid; %d lan chen ngau nhien (seed), %d box loi moi muc moi lan" %
             (n_boxes, seeds, N_PER_LEVEL),
             "- Recall = ty le box chen loi bi gan co ERROR/WARNING (cot 'ERROR' chi tinh ERROR)",
             "- Precision can duoi: moi box bi co khong nam trong so box chen deu tinh la FP, "
             "ke ca co tren GT goc (co the la loi that cua nuScenes)", ""]
    for issue, r in res.items():
        tp, fp = r["tp"], r["fp"]
        prec = 100.0 * tp / (tp + fp) if tp + fp else float("nan")
        lines += ["## %s" % issue, "",
                  "Co tren GT goc (chua chen): **%d** box. Precision can duoi: **%.0f%%** (TP=%d, FP=%d)" %
                  (r["clean_flags"], prec, tp, fp), "",
                  "| Muc | So box | Recall (>=WARNING) | Recall (ERROR) |" +
                  (" Recall (BOX_OFFSET hoac LOW_LIDAR_PTS) |" if issue == "BOX_OFFSET" else ""),
                  "|---|---|---|---|" + ("---|" if issue == "BOX_OFFSET" else "")]
        for label, (tot, anyc, errc, uni) in r["levels"].items():
            lines.append("| %s | %d | %.0f%% | %.0f%% |%s" % (
                label, tot, 100.0 * anyc / tot, 100.0 * errc / tot,
                " %.0f%% |" % (100.0 * uni / tot) if issue == "BOX_OFFSET" else ""))
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--config")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--out", default=str(paths.REPORTS / "eval_report.md"))
    args = ap.parse_args()
    if args.config:
        qc.apply_config(args.config)
    ctx = Ctx(args.dataroot, args.version)
    try:
        res = evaluate(ctx, args.seeds)
    finally:
        ctx.close()
    text = render(res, args.seeds, len(ctx.anns))
    with open(paths.ensure_parent(args.out), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()

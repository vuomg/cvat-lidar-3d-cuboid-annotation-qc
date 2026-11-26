#!/usr/bin/env python3
"""Do chi so 'IoU 3D truoc/sau khi dung tool' cua goi y sua (fixes.py).

Moi kich ban: chen loi vao box GT, chay qc, ap goi y len cac box bi co, so IoU 3D voi GT:
  size    : nhan kich thuoc x1.6 hoac x0.5
  heading : lat yaw 180 do (xe dang chay)
  shift   : dich box 1.2 m theo huong ngau nhien, TINH LAI num_lidar_pts tu point cloud that

  python -m cuboidqc.evaluation.fix_impact --dataroot V:\\data\\nuscenes --version v1.0-mini
"""
import argparse
import copy
import math
import random

from cuboidqc.core import boxfit as boxfit
from cuboidqc.evaluation import nuscenes as ev
from cuboidqc.core import fixes as fixes
from cuboidqc.core import lidar as lidar
from cuboidqc.core import qc as qc

N = 80


def iou(a, b):
    return qc.overlap_3d(a, b)[0]


def yaw_err(a, b):
    """Sai lech goc yaw (do) - IoU 3D khong nhin thay loi lat 180 do vi hop chu nhat doi xung."""
    return math.degrees(qc.angle_diff(qc.yaw_of(a["rotation"]), qc.yaw_of(b["rotation"])))


def count_pts(pts, a):
    box = {"translation": a["translation"], "size": a["size"], "yaw": qc.yaw_of(a["rotation"])}
    return sum(1 for p in pts if lidar.in_box(p, box))


def scenario(ctx, lid, name, rng):
    anns = copy.deepcopy(ctx.anns)
    gt = {a["token"]: a for a in ctx.anns}
    by = {a["token"]: a for a in anns}
    if name == "size":
        pool = [t for t in by if ctx.cat[t] in ("vehicle.car", "human.pedestrian.adult")]
        toks = rng.sample(pool, N)
        for i, t in enumerate(toks):
            f = 1.6 if i % 2 == 0 else 0.5
            by[t]["size"] = [x * f for x in by[t]["size"]]
        issues = {"BAD_SIZE"}
    elif name == "heading":
        pool = [t for t in by if ctx.cat[t] == "vehicle.car" and ctx.speed(by[t]) >= 3.5]
        toks = rng.sample(pool, N)
        for t in toks:
            fixes_yaw = qc.yaw_of(by[t]["rotation"]) + math.pi
            by[t]["rotation"] = [math.cos(fixes_yaw / 2), 0.0, 0.0, math.sin(fixes_yaw / 2)]
        issues = {"HEADING_REVERSED"}
    else:   # shift
        pool = [t for t in by if lid.available(by[t]["sample_token"])
                and ((ctx.cat[t] == "vehicle.car" and (by[t].get("num_lidar_pts") or 0) >= 40)
                     or (ctx.cat[t] == "human.pedestrian.adult" and (by[t].get("num_lidar_pts") or 0) >= 15))]
        toks = rng.sample(pool, N)
        for t in toks:
            ang = rng.uniform(0, 2 * math.pi)
            by[t]["translation"] = [by[t]["translation"][0] + 1.2 * math.cos(ang),
                                    by[t]["translation"][1] + 1.2 * math.sin(ang), by[t]["translation"][2]]
            by[t]["num_lidar_pts"] = boxfit.count_in_box(lid.points_np(by[t]["sample_token"]), by[t])
        issues = {"LOW_LIDAR_PTS", "BOX_OFFSET"}

    c = {}
    rows = ctx.run(anns, ctx_out=c)
    sugg = fixes.build_suggestions(c)
    fixes.add_lidar_suggestions(c, rows, sugg, lid)
    flagged = {r[1] for r in rows if r[3] in issues and r[4] in ("ERROR", "WARNING")}

    metric = yaw_err if name == "heading" else iou
    before_all, after_all = [], []
    before_f, after_f = [], []
    n_flag = n_fix = 0
    for t in toks:
        b0 = metric(gt[t], by[t])
        before_all.append(b0)
        res = b0
        if t in flagged:
            n_flag += 1
            fix = next((sugg[(t, i)] for i in issues if (t, i) in sugg and sugg[(t, i)].get("box")), None)
            if fix:
                n_fix += 1
                res = metric(gt[t], fixes.apply_fix(by[t], fix))
                before_f.append(b0)
                after_f.append(res)
        after_all.append(res)
    m = lambda v: sum(v) / len(v) if v else float("nan")
    if name == "heading":      # sai so goc: cang thap cang tot
        improved = sum(1 for x, y in zip(before_f, after_f) if y < x - 2.0)
    else:
        improved = sum(1 for x, y in zip(before_f, after_f) if y > x + 0.02)
    return {"n": len(toks), "flag": n_flag, "fix": n_fix,
            "iou_before": m(before_all), "iou_after": m(after_all),
            "fix_before": m(before_f), "fix_after": m(after_f), "improved": improved}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    ctx = ev.Ctx(args.dataroot, args.version)
    lid = lidar.Lidar(args.dataroot, args.version)
    names = {"size": "Sai kich thuoc (x1.6 / x0.5)", "heading": "Nguoc huong (lat 180 do) - do bang SAI SO GOC yaw",
             "shift": "Lech vi tri 1.2 m (diem tinh lai tu LiDAR that)"}
    try:
        print("| Kich ban | So box loi | Bi co | Co goi y box | IoU3D truoc | IoU3D sau (toan bo) | "
              "IoU truoc / sau (rieng box duoc sua) | Cai thien |")
        print("|---|---|---|---|---|---|---|---|")
        for key in ("size", "heading", "shift"):
            r = scenario(ctx, lid, key, random.Random(args.seed))
            fmt = "%.0f deg" if key == "heading" else "%.2f"
            print(("| %s | %d | %d | %d | " + fmt + " | " + fmt + " | " + fmt + " -> " + fmt + " | %d/%d |") % (
                names[key], r["n"], r["flag"], r["fix"], r["iou_before"], r["iou_after"],
                r["fix_before"], r["fix_after"], r["improved"], r["fix"]))
    finally:
        ctx.close()


if __name__ == "__main__":
    main()

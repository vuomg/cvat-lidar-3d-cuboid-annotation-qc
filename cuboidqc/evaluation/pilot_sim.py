#!/usr/bin/env python3
"""MO PHONG pilot (KHONG phai ket qua thuc nghiem voi nguoi that).

Mo hinh ghep cap tren cung bo annotation co loi, hai quy trinh:
  baseline : annotator nop -> reviewer duyet -> bi tra lai neu thay loi -> sua -> duyet lai ...
  pilot    : annotator chay qc.py + ap goi y tren cac co, sau do cung quy trinh review nhu baseline

Cac xac suat reviewer/annotator duoi day la GIA DINH (nhom dau file), khong do duoc. Ket qua tool
(box nao bi co, goi y sua co dung khong) thi do thuc tren du lieu nuScenes that bang qc.py/fixes.py.
Script in them bang do nhay voi gia dinh reviewer.

  python -m cuboidqc.evaluation.pilot_sim --dataroot V:\\data\\nuscenes --version v1.0-mini [--config config.json]
"""
import argparse
import copy
import math
import random
import statistics
from cuboidqc import paths

from cuboidqc.core import boxfit as boxfit
from cuboidqc.evaluation import nuscenes as ev
from cuboidqc.core import fixes as fixes
from cuboidqc.core import lidar as lidar
from cuboidqc.core import qc as qc

# ---- GIA DINH (khong do duoc) ---------------------------------------------
ERR_RATE = {"size": 0.02, "flip": 0.02, "dup": 0.005, "shift": 0.02}   # ty le loi cua annotator / box
P_REVIEWER_FINDS = {"size": 0.5, "flip": 0.4, "dup": 0.8, "shift": 0.5}  # reviewer thay 1 loi / vong duyet
P_FIX_AFTER_RETURN = 0.9     # annotator sua dung loi bi tra lai
P_FOLLOW_TOOL = 0.9          # annotator lam theo co/goi y cua tool
P_REVIEW_FIX = 0.6           # co chi la 'kiem tra thu cong' -> annotator tu sua dung
MAX_RETURNS = 6
GOOD_IOU = 0.7               # box coi la dung neu IoU 3D co huong >= 0.7
# ---------------------------------------------------------------------------
ISSUE_OF = {"size": ("BAD_SIZE",), "flip": ("HEADING_REVERSED",), "dup": ("OVERLAP",),
            "shift": ("BOX_OFFSET", "LOW_LIDAR_PTS")}


def flagged_by(flagged, typ, tok):
    return any(tok in flagged.get(i, set()) for i in ISSUE_OF[typ])


def suggestion_for(sugg, typ, tok):
    for i in ISSUE_OF[typ]:
        fx = sugg.get((tok, i))
        if fx and fx.get("box"):
            return fx
    return next((sugg[(tok, i)] for i in ISSUE_OF[typ] if (tok, i) in sugg), None)


def oriented_iou(gt, a):
    """IoU 3D, bang 0 neu yaw lech > 90 do (IoU thuan khong thay duoc loi lat 180 do)."""
    if a is None:
        return 0.0
    if qc.angle_diff(qc.yaw_of(gt["rotation"]), qc.yaw_of(a["rotation"])) > math.pi / 2:
        return 0.0
    return qc.overlap_3d(gt, a)[0]


def inject(ctx, lid, rng):
    anns = copy.deepcopy(ctx.anns)
    by = {a["token"]: a for a in anns}
    errs, dups = {}, []
    for t, a in list(by.items()):
        cat = ctx.cat[t]
        r = rng.random()
        acc = 0.0
        if cat in ("vehicle.car", "human.pedestrian.adult"):
            acc += ERR_RATE["size"]
            if r < acc:
                f = rng.choice([rng.uniform(1.3, 1.8), rng.uniform(0.5, 0.7)])
                a["size"] = [x * f for x in a["size"]]
                errs[t] = "size"
                continue
        if cat == "vehicle.car" and ctx.speed(a) >= 3.5:
            acc += ERR_RATE["flip"]
            if r < acc:
                y = qc.yaw_of(a["rotation"]) + math.pi
                a["rotation"] = [math.cos(y / 2), 0.0, 0.0, math.sin(y / 2)]
                errs[t] = "flip"
                continue
        if cat == "vehicle.car" and a["size"][1] > 3:
            acc += ERR_RATE["dup"]
            if r < acc:
                yaw = qc.yaw_of(a["rotation"])
                d = copy.deepcopy(a)
                d["token"] = "DUP%05d" % len(dups)
                d["translation"] = [a["translation"][0] + math.cos(yaw) * a["size"][1] * 0.3,
                                    a["translation"][1] + math.sin(yaw) * a["size"][1] * 0.3,
                                    a["translation"][2]]
                d["prev"] = d["next"] = ""
                dups.append(d)
                errs[d["token"]] = "dup"
                continue
        if lid.available(a["sample_token"]) and (
                (cat == "vehicle.car" and (a.get("num_lidar_pts") or 0) >= 40)
                or (cat == "human.pedestrian.adult" and (a.get("num_lidar_pts") or 0) >= 15)):
            acc += ERR_RATE["shift"]
            if r < acc:
                ang = rng.uniform(0, 2 * math.pi)
                a["translation"] = [a["translation"][0] + 1.2 * math.cos(ang),
                                    a["translation"][1] + 1.2 * math.sin(ang), a["translation"][2]]
                box = {"translation": a["translation"], "size": a["size"], "yaw": qc.yaw_of(a["rotation"])}
                a["num_lidar_pts"] = boxfit.count_in_box(lid.points_np(a["sample_token"]), a)
                errs[t] = "shift"
    return anns + dups, errs


def review_loop(bad, rng, rev_scale):
    """bad: set token con loi. Tra (so lan bi tra lai, set loi con sot khi duoc nhan, set da sua)."""
    bad, fixed = dict(bad), set()
    returns = 0
    while True:
        found = [t for t, typ in bad.items() if rng.random() < min(1.0, P_REVIEWER_FINDS[typ] * rev_scale)]
        if not found or returns >= MAX_RETURNS:
            return returns, set(bad), fixed
        returns += 1
        for t in found:
            if rng.random() < P_FIX_AFTER_RETURN:
                del bad[t]
                fixed.add(t)


def simulate(ctx, lid, rng, rev_scales):
    anns, errs = inject(ctx, lid, rng)
    by = {a["token"]: a for a in anns}
    gt = ctx.by_tok
    sample_of = {t: by[t]["sample_token"] for t in errs}
    c = {}
    rows = ctx.run(anns, ctx_out=c)
    sugg = fixes.build_suggestions(c)
    fixes.add_lidar_suggestions(c, rows, sugg, lid)
    flagged = {}
    for r in rows:
        if r[4] in ("ERROR", "WARNING"):
            flagged.setdefault(r[3], set()).add(r[1])

    # ---- buoc tu kiem tra voi tool: trang thai moi box loi ----
    state, still_bad = {}, {}
    n_total_flags = len({r[1] for r in rows if r[4] in ("ERROR", "WARNING")})
    for t, typ in errs.items():
        st = by[t]
        if flagged_by(flagged, typ, t) and rng.random() < P_FOLLOW_TOOL:
            fx = suggestion_for(sugg, typ, t)
            if typ == "dup":
                st = None                                           # xoa box trung
            elif fx and fx.get("box"):
                st = fixes.apply_fix(by[t], fx)
            elif rng.random() < P_REVIEW_FIX:
                st = gt[t]                                          # tu sua sau khi duoc nhac
        state[t] = st
        good = (st is None) if typ == "dup" else oriented_iou(gt[t], st) >= GOOD_IOU
        if not good:
            still_bad[t] = typ

    tasks = {}
    for t in errs:
        tasks.setdefault(sample_of[t], []).append(t)
    n_tasks = len({a["sample_token"] for a in anns})

    def iou_of(st_map, tokens):
        v = [oriented_iou(gt[t], st_map[t]) for t in tokens if errs[t] != "dup"]
        return v

    out = {}
    for scale in rev_scales:
        base_ret, tool_ret, base_res, tool_res = [], [], [], []
        iou_final_b, iou_final_t = [], []
        for s_tok, toks in tasks.items():
            rb, resb, fixb = review_loop({t: errs[t] for t in toks}, rng, scale)
            rt, rest, fixt = review_loop({t: errs[t] for t in toks if t in still_bad}, rng, scale)
            base_ret.append(rb); tool_ret.append(rt)
            base_res.append(len(resb)); tool_res.append(len(rest))
            for t in toks:
                if errs[t] == "dup":
                    continue
                iou_final_b.append(1.0 if t in fixb else oriented_iou(gt[t], by[t]))
                after_tool = state[t]
                iou_final_t.append(1.0 if t in fixt else oriented_iou(gt[t], after_tool))
        zeros = [0] * (n_tasks - len(tasks))       # task khong co loi nao
        out[scale] = {"base_ret": base_ret + zeros, "tool_ret": tool_ret + zeros,
                      "base_res": base_res + zeros, "tool_res": tool_res + zeros,
                      "iou_final_b": iou_final_b, "iou_final_t": iou_final_t}
    n_err = len(errs)
    iou_init = iou_of(by, [t for t in errs])
    iou_after_tool = iou_of(state, [t for t in errs])
    det = {typ: (sum(1 for t, y in errs.items() if y == typ and flagged_by(flagged, typ, t)),
                 sum(1 for y in errs.values() if y == typ)) for typ in ERR_RATE}
    return {"out": out, "n_err": n_err, "n_tasks": n_tasks, "iou_init": iou_init,
            "iou_after_tool": iou_after_tool, "det": det, "n_flags": n_total_flags,
            "n_boxes": len(anns), "still_bad": len(still_bad)}


def mean(v):
    return statistics.fmean(v) if v else float("nan")


def boot_ci(diffs, rng, n=1000):
    ms = sorted(mean([rng.choice(diffs) for _ in diffs]) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def render(runs, rev_scales, rng):
    n_runs = len(runs)
    lines = ["# MO PHONG pilot QC cuboid 3D (KHONG phai thuc nghiem voi nguoi that)", "",
             "Ghep cap: cung bo annotation co loi, hai quy trinh (baseline vs co tool). %d lan mo phong, %d task (frame) moi lan, "
             "%d box moi lan." % (n_runs, runs[0]["n_tasks"], runs[0]["n_boxes"]), "",
             "## Gia dinh chua do duoc", "",
             "- Ty le loi cua annotator / box: %s" % ERR_RATE,
             "- Xac suat reviewer thay 1 loi moi vong: %s" % P_REVIEWER_FINDS,
             "- Annotator sua dung sau khi bi tra lai: %.0f%%; lam theo tool: %.0f%%; co 'kiem tra thu cong' -> tu sua dung: %.0f%%" %
             (100 * P_FIX_AFTER_RETURN, 100 * P_FOLLOW_TOOL, 100 * P_REVIEW_FIX),
             "- Box duoc coi la dung neu IoU 3D co huong >= %.1f" % GOOD_IOU, "",
             "## Phan do that: tool tren loi mo phong", ""]
    det = {k: [sum(r["det"][k][0] for r in runs), sum(r["det"][k][1] for r in runs)] for k in ERR_RATE}
    lines += ["| Loai loi | So loi | Tool bao co |", "|---|---|---|"]
    for k, (a, b) in det.items():
        lines.append("| %s | %d | %d (%.0f%%) |" % (k, b, a, 100.0 * a / max(b, 1)))
    iou_i = mean([x for r in runs for x in r["iou_init"]])
    iou_t = mean([x for r in runs for x in r["iou_after_tool"]])
    lines += ["", "IoU 3D co huong cua cac box loi: **%.2f** (luc nop) -> **%.2f** (sau khi annotator dung tool, TRUOC review)" % (iou_i, iou_t), ""]
    lines += ["Trung binh moi lan: %.0f box bi co (%.1f%% tong box), %.1f%% loi con sot sau buoc tu kiem tra" %
              (mean([r["n_flags"] for r in runs]), 100 * mean([r["n_flags"] / r["n_boxes"] for r in runs]),
               100 * mean([r["still_bad"] / max(r["n_err"], 1) for r in runs])), ""]
    lines += ["## Ket qua theo gia dinh do nhay cua reviewer (nhan voi he so)", "",
              "| He so reviewer | So vong tra lai / task: baseline | co tool | Giam | 95% CI cua chenh lech | Loi sot / task: baseline -> co tool | IoU cuoi: baseline -> co tool |",
              "|---|---|---|---|---|---|---|"]
    for scale in rev_scales:
        b = [x for r in runs for x in r["out"][scale]["base_ret"]]
        t = [x for r in runs for x in r["out"][scale]["tool_ret"]]
        rb = [x for r in runs for x in r["out"][scale]["base_res"]]
        rt = [x for r in runs for x in r["out"][scale]["tool_res"]]
        ib = [x for r in runs for x in r["out"][scale]["iou_final_b"]]
        it = [x for r in runs for x in r["out"][scale]["iou_final_t"]]
        diffs = [x - y for x, y in zip(b, t)]
        lo, hi = boot_ci(diffs, rng)
        lines.append("| x%.1f | %.2f | %.2f | %.0f%% | [%.2f, %.2f] | %.2f -> %.2f | %.2f -> %.2f |" % (
            scale, mean(b), mean(t), 100 * (1 - mean(t) / mean(b)) if mean(b) else 0, lo, hi,
            mean(rb), mean(rt), mean(ib), mean(it)))
    lines += ["", "## Dien giai", "",
              "- Day la uoc luong *neu* cac gia dinh dung. No cho biet tool co kha nang giam bao nhieu vong tra lai khi biet "
              "do phu loi cua tool, KHONG thay the pilot voi annotator that (xem PILOT.md).",
              "- Cac loi tool khong bat duoc (vi du lech vi tri nhe vi con du diem) van nam trong quy trinh review nhu cu.",
              "- Tool khong lam reviewer 'thay' them loi: so loi sot khi duoc nhan phan anh viec box da duoc tool sua truoc khi den reviewer.",
              ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--config")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", default=str(paths.REPORTS / "pilot_sim_report.md"))
    args = ap.parse_args()
    if args.config:
        qc.apply_config(args.config)
    ctx = ev.Ctx(args.dataroot, args.version)
    lid = lidar.Lidar(args.dataroot, args.version)
    scales = [0.6, 1.0, 1.4]
    try:
        runs = [simulate(ctx, lid, random.Random(s), scales) for s in range(args.runs)]
    finally:
        ctx.close()
    text = render(runs, scales, random.Random(123))
    with open(paths.ensure_parent(args.out), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()

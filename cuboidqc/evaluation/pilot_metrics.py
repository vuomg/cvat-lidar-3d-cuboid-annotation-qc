#!/usr/bin/env python3
"""Phan tich so lieu PILOT THAT: so vong bi tra lai va IoU 3D truoc/sau khi dung tool.

Dau vao: CSV (xem pilot_log_template.csv), moi dong = 1 task (1 lan annotator nop 1 task):
  task_id,group,annotator_id,rounds_returned,iou3d_mean,minutes
  - group: baseline | tool
  - rounds_returned: so lan reviewer tra lai truoc khi duoc nhan (0 = nhan ngay)
  - iou3d_mean (tuy chon): IoU 3D trung binh cua nhan CUOI CUNG so voi gold, tinh bang evaluate_gold()
  - minutes (tuy chon): thoi gian lam task

Neu cung task_id xuat hien o ca hai nhom (thiet ke ghep cap / crossover) -> phan tich ghep cap.
Output: bang tom tat, chenh lech, 95% CI (bootstrap theo task), p-value (hoan vi), co so mau can thiet.

  python -m cuboidqc.evaluation.pilot_metrics pilot_log.csv [--out pilot_result.md]
"""
import argparse
import csv
import math
import random
import statistics
from collections import defaultdict


def mean(v):
    return statistics.fmean(v) if v else float("nan")


def sd(v):
    return statistics.stdev(v) if len(v) > 1 else float("nan")


def read(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["group"] not in ("baseline", "tool"):
                raise SystemExit("group phai la baseline hoac tool: %r" % r["group"])
            rows.append({"task": r["task_id"], "group": r["group"], "ann": r.get("annotator_id", ""),
                         "rounds": float(r["rounds_returned"]),
                         "iou": float(r["iou3d_mean"]) if r.get("iou3d_mean") not in (None, "") else None,
                         "min": float(r["minutes"]) if r.get("minutes") not in (None, "") else None})
    return rows


def split(rows, key):
    b = [r[key] for r in rows if r["group"] == "baseline" and r[key] is not None]
    t = [r[key] for r in rows if r["group"] == "tool" and r[key] is not None]
    return b, t


def paired_diffs(rows, key):
    by = defaultdict(dict)
    for r in rows:
        if r[key] is not None:
            by[r["task"]].setdefault(r["group"], []).append(r[key])
    return [mean(g["baseline"]) - mean(g["tool"]) for g in by.values() if "baseline" in g and "tool" in g]


def boot_ci(values_fn, rng, n=2000):
    ms = sorted(values_fn() for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def compare(rows, key, rng):
    """Tra dict thong ke chenh lech baseline - tool (duong = tool tot hon voi rounds/minutes)."""
    b, t = split(rows, key)
    if len(b) < 2 or len(t) < 2:
        return None
    pd = paired_diffs(rows, key)
    paired = len(pd) >= 2 and len(pd) >= 0.8 * min(len(b), len(t))
    if paired:
        diff = mean(pd)
        lo, hi = boot_ci(lambda: mean([rng.choice(pd) for _ in pd]), rng)
        obs = abs(diff)
        cnt = 0
        for _ in range(5000):    # hoan vi dau cua tung cap
            if abs(mean([d if rng.random() < 0.5 else -d for d in pd])) >= obs:
                cnt += 1
        p = (cnt + 1) / 5001
    else:
        diff = mean(b) - mean(t)
        lo, hi = boot_ci(lambda: mean([rng.choice(b) for _ in b]) - mean([rng.choice(t) for _ in t]), rng)
        allv, nb = b + t, len(b)
        cnt = 0
        for _ in range(5000):
            rng.shuffle(allv)
            if abs(mean(allv[:nb]) - mean(allv[nb:])) >= abs(diff):
                cnt += 1
        p = (cnt + 1) / 5001
    return {"mean_b": mean(b), "mean_t": mean(t), "sd_b": sd(b), "sd_t": sd(t), "n_b": len(b), "n_t": len(t),
            "diff": diff, "ci": (lo, hi), "p": p, "paired": paired, "n_pairs": len(pd)}


def sample_size(delta, sigma, alpha_z=1.96, power_z=0.84):
    """So task moi nhom de phat hien chenh lech delta (so sanh 2 trung binh, SD chung sigma)."""
    return math.ceil(2 * ((alpha_z + power_z) ** 2) * sigma ** 2 / delta ** 2)


def render(rows, rng):
    lines = ["# Ket qua pilot QC cuboid 3D", ""]
    g = defaultdict(int)
    for r in rows:
        g[r["group"]] += 1
    lines += ["So task: baseline=%d, tool=%d; so annotator: %d" %
              (g["baseline"], g["tool"], len({r["ann"] for r in rows if r["ann"]})), ""]
    lines += ["| Chi so | Baseline | Co tool | Chenh lech (baseline - tool) | 95% CI | p | Kieu phan tich |",
              "|---|---|---|---|---|---|---|"]
    specs = [("rounds", "So vong bi tra lai / task (thap hon la tot)"),
             ("iou", "IoU 3D so voi gold (cao hon la tot)"),
             ("min", "Thoi gian / task (phut)")]
    note_sd = None
    for key, label in specs:
        c = compare(rows, key, rng)
        if not c:
            continue
        if key == "rounds":
            note_sd = max(c["sd_b"], c["sd_t"])
        lines.append("| %s | %.2f (SD %.2f, n=%d) | %.2f (SD %.2f, n=%d) | %+.2f | [%+.2f, %+.2f] | %s | %s |" % (
            label, c["mean_b"], c["sd_b"], c["n_b"], c["mean_t"], c["sd_t"], c["n_t"],
            c["diff"], c["ci"][0], c["ci"][1], "<0.001" if c["p"] < 0.001 else "%.3f" % c["p"],
            "ghep cap (%d cap)" % c["n_pairs"] if c["paired"] else "hai nhom doc lap"))
    c = compare(rows, "rounds", rng)
    if c and c["mean_b"] > 0:
        lines += ["", "Giam so vong tra lai: **%.0f%%** (%.2f -> %.2f)" % (100 * (1 - c["mean_t"] / c["mean_b"]),
                                                                        c["mean_b"], c["mean_t"])]
    if note_sd:
        lines += ["", "Co so mau: voi SD vong tra lai ~ %.2f, can ~%d task / nhom de phat hien giam 0.5 vong (alpha=.05, power=.8)." %
                  (note_sd, sample_size(0.5, note_sd))]
    lines += ["", "Luu y: p-value va CI chi dung khi task duoc chia ngau nhien giua hai nhom va reviewer khong biet task thuoc nhom nao."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--out", default="pilot_result.md")
    args = ap.parse_args()
    text = render(read(args.csv), random.Random(0))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()

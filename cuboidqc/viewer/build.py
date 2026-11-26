#!/usr/bin/env python3
"""Sinh viewer.html (mot file HTML tu du, mo bang trinh duyet) tu ket qua qc.py.

Hien thi tung loi tren BEV: box bi co (do), goi y sua (xanh), diem LiDAR, box lan can.
Annotator bam 'Loi that' / 'Bao nham' / 'Bo qua'; nhan luu trong trinh duyet, xuat ra decisions.csv.

  python -m cuboidqc.viewer.build --dataroot V:\\data\\nuscenes --version v1.0-mini --out viewer.html [--max 400]
"""
import argparse
import json
import os
import random
import re
from collections import defaultdict
from cuboidqc import paths

from cuboidqc.core import fixes as fixes
from cuboidqc.core import lidar as lidar
from cuboidqc.core import qc as qc

WIN = 16.0            # nua canh cua so hien thi quanh box (m)
NEAR_R, NEAR_CAP, FAR_CAP = 6.0, 1200, 700
SEV = {"ERROR": 0, "WARNING": 1}


def rel_box(box, c):
    return {"translation": [box["translation"][0] - c[0], box["translation"][1] - c[1],
                            box["translation"][2] - c[2]],
            "size": [round(x, 3) for x in box["size"]], "yaw": round(box["yaw"], 4)}


def merge_rows(rows):
    """Gop cac dong cung (annotation, issue): BAD_SIZE co the sinh den 3 dong (w, l, h)."""
    merged = {}
    for sample, tok, cat, issue, sev, detail in rows:
        if sev == "INFO":
            continue
        k = (tok, issue)
        if k not in merged:
            merged[k] = [sample, tok, cat, issue, sev, detail]
        else:
            m = merged[k]
            m[4] = min(m[4], sev, key=lambda s: SEV[s])
            m[5] += "; " + detail
    return list(merged.values())


def pick_items(merged, max_items):
    by_issue = defaultdict(list)
    for r in merged:
        by_issue[r[3]].append(r)
    cap = max(1, max_items // max(len(by_issue), 1))
    chosen = []
    for issue, lst in by_issue.items():
        lst.sort(key=lambda r: SEV[r[4]])
        chosen += lst[:cap]
    rest = [r for lst in by_issue.values() for r in lst[cap:]]
    rest.sort(key=lambda r: SEV[r[4]])
    chosen += rest[:max(0, max_items - len(chosen))]
    chosen.sort(key=lambda r: (SEV[r[4]], r[3]))
    return chosen


def build(root, version, max_items, report_path):
    ctx = {}
    rows = qc.run(root, version, report_path, quiet=True, ctx_out=ctx)
    sugg = fixes.build_suggestions(ctx)
    try:
        lid = lidar.Lidar(root, version)
    except FileNotFoundError:
        lid = None
    fixes.add_lidar_suggestions(ctx, rows, sugg, lid)

    by_tok = {a["token"]: a for a in ctx["anns"]}
    cat_of = dict(zip((a["token"] for a in ctx["anns"]), ctx["cats"]))
    by_sample = defaultdict(list)
    for a in ctx["anns"]:
        if "translation" in a:
            by_sample[a["sample_token"]].append(a)

    merged = merge_rows(rows)
    chosen = pick_items(merged, max_items)
    rng = random.Random(0)
    items = []
    n_pts = 0
    for sample, tok, cat, issue, sev, detail in chosen:
        a = by_tok[tok]
        c = a["translation"]
        box_abs = fixes.box_of(a)
        fix = sugg.get((tok, issue))
        pts = lid.points_global(sample) if lid else None
        near = []
        if pts is not None:
            near = [p for p in pts if abs(p[0] - c[0]) <= WIN and abs(p[1] - c[1]) <= WIN
                    and -3 <= p[2] - c[2] <= 4]
            n_pts += 1
        inner = [p for p in near if (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 <= NEAR_R ** 2]
        outer = [p for p in near if (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 > NEAR_R ** 2]
        keep = (rng.sample(inner, NEAR_CAP) if len(inner) > NEAR_CAP else inner) + \
               (rng.sample(outer, FAR_CAP) if len(outer) > FAR_CAP else outer)

        partner = None
        m = re.search(r"voi ([0-9a-f]{8}) ", detail) if issue == "OVERLAP" else None
        if m:
            partner = m.group(1)
        neighbors = []
        for o in by_sample[sample]:
            if o["token"] == tok:
                continue
            if abs(o["translation"][0] - c[0]) <= WIN * 1.3 and abs(o["translation"][1] - c[1]) <= WIN * 1.3:
                nb = rel_box(fixes.box_of(o), c)
                nb["partner"] = bool(partner and o["token"].startswith(partner))
                neighbors.append(nb)

        item = {"issue": issue, "severity": sev, "category": cat, "token": tok, "sample": sample,
                "detail": detail, "box": rel_box(box_abs, c), "neighbors": neighbors,
                "has_pts": pts is not None,
                "pts_in": sum(1 for p in near if lidar.in_box(p, box_abs)) if pts is not None else a.get("num_lidar_pts"),
                "points": [[round(p[0] - c[0], 2), round(p[1] - c[1], 2), round(p[2] - c[2], 2)] for p in keep]
                          if pts is not None else None}
        if fix:
            f = {"kind": fix["kind"], "text": fix["text"], "box": None}
            if fix.get("box"):
                f["box"] = rel_box(fix["box"], c)
                f["pts_in"] = sum(1 for p in near if lidar.in_box(p, fix["box"])) if pts is not None else "?"
            item["fix"] = f
        items.append(item)
    meta = "%s (%d loi, %d frame co LiDAR)" % (version, len(items), n_pts)
    return {"meta": meta, "items": items}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--out", default=str(paths.DATA / "viewer.html"))
    ap.add_argument("--report", default=str(paths.DATA / "report.csv"))
    ap.add_argument("--max", type=int, default=400, help="so loi toi da dua vao viewer")
    ap.add_argument("--config")
    args = ap.parse_args()
    if args.config:
        qc.apply_config(args.config)
    data = build(args.dataroot, args.version, args.max, args.report)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "template.html"), encoding="utf-8") as f:
        html = f.read()
    html = html.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))
    with open(paths.ensure_parent(args.out), "w", encoding="utf-8") as f:
        f.write(html)
    print("Da tao %s (%.1f MB, %d loi)" % (args.out, os.path.getsize(args.out) / 1e6, len(data["items"])))


if __name__ == "__main__":
    main()

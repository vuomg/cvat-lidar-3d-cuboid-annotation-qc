#!/usr/bin/env python3
"""Mo phong OFFLINE vong 'QC -> apply -> QC lai' tren du lieu demo (khong can CVAT), de so cac chinh sach apply.

Dung dung ham cua cvat_qc (analyze_job, plan_writeback, verify_injected, collateral_changes); chi thay phan goi
mang bang viec gop ke hoach ghi vao annotation trong bo nho.

  python -m cuboidqc.evaluation.cvat_loop --demo demo_data --profile profile.json
"""
import argparse
import copy
import json
import os
from cuboidqc import paths

from cuboidqc.cvat import runner as cq
from cuboidqc.cvat import setup as cs


def _fake_ids(labels_spec):
    label_ids = {l["name"]: i + 1 for i, l in enumerate(labels_spec)}
    attr_ids, n = {}, 100
    for l in labels_spec:
        for a in l["attributes"]:
            n += 1
            attr_ids[(l["name"], a["name"])] = n
    return label_ids, attr_ids


def merge_plan(annotations, plan):
    """Gop ke hoach (delete / update / create) vao annotation, giong cach CVAT xu ly PATCH."""
    ann = copy.deepcopy(annotations)
    del_t = {t["id"] for t in plan["delete"]["tracks"]}
    del_s = {s["id"] for s in plan["delete"]["shapes"]}
    ann["tracks"] = [t for t in ann["tracks"] if t["id"] not in del_t]
    ann["shapes"] = [s for s in ann["shapes"] if s.get("id") not in del_s]
    upd_t = {t["id"]: t for t in plan["update"]["tracks"]}
    ann["tracks"] = [upd_t.get(t["id"], t) for t in ann["tracks"]]
    upd_s = {s["id"]: s for s in plan["update"]["shapes"]}
    ann["shapes"] = [upd_s.get(s.get("id"), s) for s in ann["shapes"]]
    ann["shapes"] += plan["create"]["shapes"]
    return ann


def simulate(demo_dir, profile, policy):
    """policy: 'conservative' | 'all' (xem cvat_qc._fix_allowed)."""
    with open(os.path.join(demo_dir, "meta.json")) as f:
        meta = json.load(f)["frames"]
    with open(os.path.join(demo_dir, "labels.json")) as f:
        labels_spec = json.load(f)
    with open(os.path.join(demo_dir, "annotations.json")) as f:
        neutral = json.load(f)
    label_ids, attr_ids = _fake_ids(labels_spec)
    id2label = {v: k for k, v in label_ids.items()}
    pts = cq.load_frames_points(demo_dir, meta)
    ann = cs.build_payload(neutral, label_ids)
    for i, t in enumerate(ann["tracks"]):
        t["id"] = i + 1

    first = cq.analyze_job(ann, id2label, meta, pts, profile)
    plan = cq.plan_writeback(ann, first, label_ids, attr_ids, apply=True, apply_policy=policy)
    after_ann = merge_plan(ann, plan)
    second = cq.analyze_job(after_ann, id2label, meta, pts, profile)
    return {"first_flags": len(cq.summarize(first)), "stats": plan["stats"],
            "verify": cq.verify_injected(demo_dir, second, after_ann),
            "collateral": cq.collateral_changes(demo_dir, second),
            "second_flags": len(cq.summarize(second))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--demo", nargs="+", default=[str(paths.DEMO)], help="mot hoac nhieu thu muc demo (nhieu scene)")
    ap.add_argument("--profile", default=str(paths.PROFILE))
    args = ap.parse_args()
    print("| Scene | Chinh sach apply | Cuboid bi co (truoc -> sau) | Da ap dung | Loi chen da sua | Loi chen bo sot | "
          "Box nhan dung bi doi | IoU TB cua box bi doi voi nhan goc |")
    print("|---|---|---|---|---|---|---|---|")
    for demo, policy in [(d, p) for d in args.demo for p in ("conservative", "all")]:
        r = simulate(demo, args.profile, policy)
        v = r["verify"]
        fixed = sum(x["status"] == "fixed" for x in v)
        caught = sum(x["status"] == "caught" for x in v)
        missed = sum(x["status"] == "missed" for x in v)
        col = r["collateral"]
        miou = sum(c["iou"] for c in col["changed"]) / len(col["changed"]) if col["changed"] else float("nan")
        print("| %s | %s | %d -> %d | %d | %d / %d | %d | %d / %d | %s |" % (
            os.path.basename(demo.rstrip("/\\")), policy, r["first_flags"], r["second_flags"], r["stats"]["applied"],
            fixed, len(v), missed, len(col["changed"]), col["n"], "%.2f" % miou if col["changed"] else "-"))


if __name__ == "__main__":
    main()

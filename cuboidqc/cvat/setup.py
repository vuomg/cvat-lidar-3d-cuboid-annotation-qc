#!/usr/bin/env python3
"""Tao project + task + job demo tren CVAT (local) tu thu muc do cvat_demo.py dung ra.

  python -m cuboidqc.cvat.setup --demo demo_data [--recreate]

Dang nhap qua bien moi truong (xem cvat_client.py). Chi tao / xoa do vat mang ten 'cuboid-qc-demo'.
"""
import argparse
import io
import json
import os
import zipfile
from cuboidqc import paths

from cuboidqc.cvat.client import Client

PROJECT_NAME = "cuboid-qc-demo"


def make_zip(frames_dir):
    """Nen cac .pcd thanh mot file zip (khong nen, giu thu tu tu nhien)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for fn in sorted(os.listdir(frames_dir)):
            if fn.lower().endswith(".pcd"):
                z.write(os.path.join(frames_dir, fn), fn)
    return buf.getvalue()


def build_payload(neutral, label_ids):
    """annotations.json (trung lap) -> body PUT /api/jobs/{id}/annotations."""
    tracks = []
    for t in neutral["tracks"]:
        shapes = [{"type": "cuboid", "frame": s["frame"], "points": s["points"], "occluded": s["occluded"],
                   "outside": s["outside"], "z_order": 0, "rotation": 0.0, "attributes": [], "source": "manual"}
                  for s in sorted(t["shapes"], key=lambda s: s["frame"])]
        tracks.append({"frame": shapes[0]["frame"], "label_id": label_ids[t["label"]], "group": 0,
                       "source": "manual", "attributes": [], "shapes": shapes})
    return {"version": 0, "tags": [], "shapes": [], "tracks": tracks}


def label_maps(labels):
    """labels tu GET /api/labels -> ({ten: id}, {(ten_label, ten_attr): spec_id})."""
    ids = {l["name"]: l["id"] for l in labels}
    attrs = {(l["name"], a["name"]): a["id"] for l in labels for a in l.get("attributes", [])}
    return ids, attrs


def setup(demo_dir, recreate=False, client=None):
    c = client or Client.from_env()
    me = c.me()
    print("Dang nhap: %s (CVAT %s)" % (me.get("username"), c.host))
    with open(os.path.join(demo_dir, "labels.json"), encoding="utf-8") as f:
        labels_spec = json.load(f)
    with open(os.path.join(demo_dir, "annotations.json"), encoding="utf-8") as f:
        neutral = json.load(f)

    existing = c.find_project(PROJECT_NAME)
    if existing and recreate:
        print("Xoa project cu '%s' (id %d) va cac task ben trong" % (PROJECT_NAME, existing["id"]))
        c.delete_project(existing["id"])
        existing = None
    if existing:
        raise SystemExit("Project '%s' da ton tai (id %d). Dung --recreate de tao lai." % (PROJECT_NAME, existing["id"]))

    project = c.create_project(PROJECT_NAME, labels_spec)
    pid = project["id"]
    label_ids, attr_ids = label_maps(c.labels(project_id=pid))
    task = c.create_task("scene demo", pid)
    tid = task["id"]
    print("Tai %d frame len task %d ..." % (len(os.listdir(os.path.join(demo_dir, "frames"))), tid))
    c.upload_task_data(tid, [("frames.zip", make_zip(os.path.join(demo_dir, "frames")))])
    jobs = c.task_jobs(tid)
    jid = jobs[0]["id"]
    c.put_annotations(jid, build_payload(neutral, label_ids))
    ids = {"host": c.host, "project_id": pid, "task_id": tid, "job_id": jid,
           "labels": label_ids, "attrs": {"%s|%s" % k: v for k, v in attr_ids.items()}}
    with open(os.path.join(demo_dir, "cvat_ids.json"), "w") as f:
        json.dump(ids, f, indent=1)
    print("Xong. Mo job: %s" % c.job_url(tid, jid))
    return ids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--demo", default=str(paths.DEMO))
    ap.add_argument("--recreate", action="store_true", help="xoa project demo cu roi tao lai")
    args = ap.parse_args()
    setup(args.demo, args.recreate)


if __name__ == "__main__":
    main()

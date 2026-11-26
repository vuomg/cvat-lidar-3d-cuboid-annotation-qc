#!/usr/bin/env python3
"""Tao task 'calibration' trong project demo de KIEM CHUNG quy uoc cuboid CVAT bang mat:

Frame duy nhat chua cac cum diem danh dau truc va hai cuboid bat doi xung (points: sx=8, sy=2, sz=2):
  - cum DAC o (+25, 0)            : danh dau chieu +x
  - 3 cum nho o (0, +20/+23/+26)  : danh dau chieu +y (3 cum = +y, 1 cum = +x)
  - Car   tai (0, 0),   rz = 0      : neu sx la chieu dai doc +x thi hop nam NGANG doc +x
  - Truck tai (0, -14), rz = +45 do : quay nguoc chieu kim dong ho (nhin tu tren xuong) neu rz > 0 la CCW
  - cum diem day dac o dau +x cua hop Car: de xem CVAT ve dau mui ten / dau phia truoc o dau nao

  python -m cuboidqc.cvat.calibrate --demo demo_data
"""
import argparse
import json
import math
import os

import numpy as np
from cuboidqc import paths

from cuboidqc.cvat import adapter as ca
from cuboidqc.cvat import demo as cvat_demo
from cuboidqc.cvat import setup as cvat_setup
from cuboidqc.cvat.client import Client


def build(out_dir):
    rng = np.random.default_rng(0)
    os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
    pts = [np.column_stack([rng.uniform(-40, 40, 2500), rng.uniform(-40, 40, 2500), rng.normal(0, 0.03, 2500)])]

    def blob(c, r, n):
        pts.append(np.array(c) + rng.normal(0, r, (n, 3)))
    blob((25, 0, 1.0), 0.8, 600)                                  # +x: cum dac
    for y in (20, 23, 26):                                        # +y: 3 cum nho
        blob((0, y, 1.0), 0.35, 120)
    pts.append(np.column_stack([rng.uniform(3.2, 3.8, 400), rng.uniform(-0.9, 0.9, 400), rng.uniform(0.2, 1.8, 400)]))
    P = np.vstack(pts)
    cvat_demo.write_pcd(os.path.join(out_dir, "frames", "000000.pcd"),
                        np.column_stack([P, np.full(len(P), 10.0)]).astype(np.float32))
    shapes = lambda p: [{"frame": 0, "points": p, "occluded": False, "outside": False}]
    ann = {"tracks": [
        {"key": "car", "label": "Car", "shapes": shapes(ca.box_to_points([0, 0, 1.0], (2.0, 8.0, 2.0), 0.0))},
        {"key": "truck", "label": "Truck", "shapes": shapes(ca.box_to_points([0, -14, 1.0], (2.0, 8.0, 2.0), math.radians(45)))},
    ]}
    with open(os.path.join(out_dir, "annotations.json"), "w") as f:
        json.dump(ann, f)
    return ann


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--demo", default=str(paths.DEMO))
    ap.add_argument("--out", default=str(paths.CALIB))
    args = ap.parse_args()
    ann = build(args.out)
    with open(os.path.join(args.demo, "cvat_ids.json")) as f:
        ids = json.load(f)
    c = Client.from_env()
    task = c.create_task("calibration", ids["project_id"])
    c.upload_task_data(task["id"], [("frames.zip", cvat_setup.make_zip(os.path.join(args.out, "frames")))])
    jid = c.task_jobs(task["id"])[0]["id"]
    c.put_annotations(jid, cvat_setup.build_payload(ann, ids["labels"]))
    print("Xong. Mo job hieu chinh: %s" % c.job_url(task["id"], jid))
    with open(os.path.join(args.out, "cvat_ids.json"), "w") as f:
        json.dump({"task_id": task["id"], "job_id": jid}, f)


if __name__ == "__main__":
    main()

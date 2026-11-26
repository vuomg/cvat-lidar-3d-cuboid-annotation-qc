#!/usr/bin/env python3
"""Sinh du lieu gia dang nuScenes (chi cac bang qc.py can) de test, co chen loi biet truoc."""
import json
import os
import random
import sys

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "synthetic")
ver = os.path.join(out, "v1.0-synth")
os.makedirs(ver, exist_ok=True)
random.seed(0)

cats = {"car": "vehicle.car", "ped": "human.pedestrian.adult", "cone": "movable_object.trafficcone"}
category = [{"token": k, "name": v} for k, v in cats.items()]
visibility = [{"token": str(i), "level": lv} for i, lv in
              enumerate(["v0-40", "v40-60", "v60-80", "v80-100"], 1)]
instance, ann, injected = [], [], {}


def add(i, cat, size, pts, vis="4", tag=None):
    tok = "ann%04d" % i
    instance.append({"token": "inst%04d" % i, "category_token": cat})
    ann.append({"token": tok, "sample_token": "s%d" % (i // 10), "instance_token": "inst%04d" % i,
                "size": size, "num_lidar_pts": pts, "visibility_token": vis})
    if tag:
        injected[tok] = tag


i = 0
for _ in range(200):
    add(i, "car", [random.gauss(1.9, .08), random.gauss(4.5, .25), random.gauss(1.7, .08)],
        random.randint(20, 400)); i += 1
for _ in range(100):
    add(i, "ped", [random.gauss(.65, .05), random.gauss(.7, .05), random.gauss(1.75, .08)],
        random.randint(8, 120)); i += 1
for _ in range(5):  # cone it mau -> dung prior
    add(i, "cone", [.4, .4, .8], 15); i += 1
# --- loi chen vao ---
add(i, "car", [1.9, 4.5, 1.7], 0, tag="LOW_LIDAR_PTS ERROR"); i += 1
add(i, "car", [1.9, 4.5, 1.7], 2, "4", tag="LOW_LIDAR_PTS ERROR"); i += 1
add(i, "car", [1.9, 4.5, 1.7], 2, "1", tag="LOW_LIDAR_PTS WARNING (bi che)"); i += 1
add(i, "car", [1.9, 12.0, 1.7], 80, tag="BAD_SIZE ERROR"); i += 1
add(i, "ped", [0.65, 0.7, 0.4], 30, tag="BAD_SIZE ERROR"); i += 1
add(i, "cone", [1.5, 1.5, 3.0], 30, tag="BAD_SIZE (prior)"); i += 1

for name, data in [("category", category), ("visibility", visibility),
                   ("instance", instance), ("sample_annotation", ann)]:
    with open(os.path.join(ver, name + ".json"), "w") as f:
        json.dump(data, f)
with open(os.path.join(out, "injected.json"), "w") as f:
    json.dump(injected, f, indent=1)
print("Da tao %d cuboid, %d loi chen vao -> %s" % (len(ann), len(injected), out))

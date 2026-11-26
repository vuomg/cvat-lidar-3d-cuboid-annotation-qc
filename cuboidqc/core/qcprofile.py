"""Profile tham chieu: thong ke tu nuScenes (kich thuoc, so diem LiDAR theo khoang cach) de QC mot job CVAT nho.

Mot job CVAT chi co vai chuc frame, khong du mau de tu tinh khoang kich thuoc / so diem ky vong,
nen ta tinh mot lan tren nuScenes (qua ten category "chuan" cua 8 class guideline) roi luu ra JSON.

  python -m cuboidqc.core.qcprofile --dataroot V:\\data\\nuscenes --version v1.0-mini --out profile.json
"""
import argparse
import json
from cuboidqc import paths

from cuboidqc.core import fixes as fixes
from cuboidqc.core import qc as qc

# category nuScenes -> category chuan (cung 8 class voi cvat-prelabel/configs/class_map.json)
NUSCENES_TO_CANON = {
    "vehicle.car": "vehicle.car",
    "vehicle.truck": "vehicle.truck",
    "vehicle.trailer": "vehicle.trailer",
    "vehicle.bus.rigid": "vehicle.bus.rigid",
    "vehicle.bus.bendy": "vehicle.bus.rigid",
    "vehicle.construction": "vehicle.construction",
    "human.pedestrian.adult": "human.pedestrian.adult",
    "human.pedestrian.child": "human.pedestrian.adult",
    "human.pedestrian.construction_worker": "human.pedestrian.adult",
    "human.pedestrian.police_officer": "human.pedestrian.adult",
    "vehicle.motorcycle": "vehicle.motorcycle",
    "vehicle.bicycle": "vehicle.motorcycle",
    "movable_object.barrier": "movable_object.barrier",
}


def build(root, version):
    categories = {c["token"]: c["name"] for c in qc.load_table(root, version, "category")}
    inst = {i["token"]: categories.get(i["category_token"], "unknown") for i in qc.load_table(root, version, "instance")}
    anns_all = qc.load_table(root, version, "sample_annotation")
    vis = {v["token"]: v["level"] for v in qc.load_table(root, version, "visibility")}
    dist_all = qc.load_distances(root, version, anns_all)
    anns, cats = [], []
    for a in anns_all:
        canon = NUSCENES_TO_CANON.get(inst.get(a["instance_token"]))
        if canon:
            anns.append(a)
            cats.append(canon)
    ranges = qc.build_size_ranges([(c, a["size"][0], a["size"][1], a["size"][2]) for c, a in zip(cats, anns)])
    expect = qc.build_pts_expect(anns, cats, dist_all, vis)
    medians = fixes.class_medians(anns, cats)
    return {
        "meta": {"source": "%s/%s" % (root, version), "n_boxes": len(anns)},
        "size_ranges": {c: {"dims": [list(d) for d in dims], "src": src} for c, (dims, src) in ranges.items()},
        "pts_expect": [{"key": list(k), "median": m, "n": n, "src": s} for k, (m, n, s) in expect.items()],
        "size_median": medians,
    }


def load(profile):
    """Dict JSON (hoac duong dan) -> (ranges, expect, medians) o dang qc.analyze can."""
    if isinstance(profile, str):
        with open(profile, encoding="utf-8") as f:
            profile = json.load(f)
    ranges = {c: (tuple(tuple(d) for d in v["dims"]), v["src"]) for c, v in profile["size_ranges"].items()}
    expect = {(e["key"][0], e["key"][1]): (e["median"], e["n"], e["src"]) for e in profile["pts_expect"]}
    return ranges, expect, profile["size_median"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--out", default=str(paths.PROFILE))
    args = ap.parse_args()
    p = build(args.dataroot, args.version)
    with open(paths.ensure_parent(args.out), "w", encoding="utf-8") as f:
        json.dump(p, f, indent=1)
    print("Da ghi %s: %d box, %d class, %d o (class, khoang cach)" %
          (args.out, p["meta"]["n_boxes"], len(p["size_ranges"]), len(p["pts_expect"])))


if __name__ == "__main__":
    main()

"""Test cho cvat_adapter / qcprofile (khong can CVAT dang chay)."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cuboidqc.cvat import adapter as ca  # noqa: E402
from cuboidqc.core import qc as qc  # noqa: E402


def cub(frame, x, y, z=0.0, rz=0.0, sx=4.0, sy=2.0, sz=1.5, occluded=False, outside=False, **kw):
    d = {"type": "cuboid", "frame": frame, "points": [x, y, z, 0, 0, rz, sx, sy, sz] + [0] * 7,
         "occluded": occluded, "outside": outside, "attributes": []}
    d.update(kw)
    return d


LABELS = {1: "Car", 2: "Pedestrian", 3: "QC_SUGGESTION"}


class TestPoints(unittest.TestCase):
    def test_default_convention_mapping(self):
        pts = ca.box_to_points([1, 2, 3], (2.0, 4.0, 1.5), 0.3)          # (w, l, h)
        self.assertEqual(len(pts), 16)
        self.assertEqual(pts[:3], [1, 2, 3])
        self.assertAlmostEqual(pts[5], 0.3)                                # rz = yaw
        self.assertEqual(pts[6:9], [4.0, 2.0, 1.5])                        # sx = l, sy = w, sz = h

    def test_roundtrip(self):
        for yaw in (0.0, 0.7, -2.5, 3.1):
            for conv in (None, {"scale_order": "wlh", "yaw_offset": math.pi / 2, "yaw_sign": -1.0}):
                pts = ca.box_to_points([5, -6, 1], (1.9, 4.5, 1.7), yaw, conv)
                t, size, y2 = ca.points_to_box(pts, conv)
                self.assertEqual(t, [5, -6, 1])
                self.assertEqual(size, (1.9, 4.5, 1.7))
                self.assertAlmostEqual(qc.angle_diff(y2, yaw), 0.0, places=9)

    def test_alternative_scale_order(self):
        conv = {"scale_order": "wlh", "yaw_offset": 0.0, "yaw_sign": 1.0}
        self.assertEqual(ca.box_to_points([0, 0, 0], (2.0, 4.0, 1.5), 0.0, conv)[6:9], [2.0, 4.0, 1.5])


class TestQuat(unittest.TestCase):
    def test_rotate_90_about_z(self):
        v = ca.rotate(ca.quat_from_yaw(math.pi / 2), [1, 0, 0])
        self.assertAlmostEqual(v[0], 0, places=9)
        self.assertAlmostEqual(v[1], 1, places=9)

    def test_qmul_adds_yaw(self):
        q = ca.qmul(ca.quat_from_yaw(0.4), ca.quat_from_yaw(0.5))
        self.assertAlmostEqual(qc.yaw_of(q), 0.9, places=9)

    def test_to_global_composition_order_noncommuting(self):
        """Ego nghieng 90 do quanh x, box quay 90 do quanh z. Huong mat truoc cua box (1,0,0):
        trong ego thanh (0,1,0); ego nghieng quanh x dua (0,1,0) -> (0,0,1) trong global.
        Neu nhan sai thu tu se ra (0,1,0)."""
        ego_q = [math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0, 0.0]
        _, q = ca.to_global([0, 0, 0], ca.quat_from_yaw(math.pi / 2), [0, 0, 0], ego_q)
        v = ca.rotate(q, [1, 0, 0])
        self.assertAlmostEqual(v[0], 0.0, places=9)
        self.assertAlmostEqual(v[1], 0.0, places=9)
        self.assertAlmostEqual(v[2], 1.0, places=9)

    def test_to_global(self):
        # ego o (10, 20), quay 90 do; box o (+1, 0) trong ego -> (10, 21) trong global, yaw box 0 -> 90 do
        t, q = ca.to_global([1, 0, 0], ca.quat_from_yaw(0.0), [10, 20, 0], ca.quat_from_yaw(math.pi / 2))
        self.assertAlmostEqual(t[0], 10, places=9)
        self.assertAlmostEqual(t[1], 21, places=9)
        self.assertAlmostEqual(qc.yaw_of(q), math.pi / 2, places=9)


class TestLoadJob(unittest.TestCase):
    def setUp(self):
        self.frames = [{"sample_token": "s%d" % i, "timestamp": i * 500000,
                        "ego_translation": [100.0 * i, 0.0, 0.0], "ego_rotation": ca.quat_from_yaw(0.0)}
                       for i in range(4)]
        self.annotations = {
            "shapes": [cub(0, 5, 5, id=77, label_id=2)],
            "tracks": [
                {"id": 10, "label_id": 1, "shapes": [cub(0, 1, 0), cub(1, 2, 0), cub(3, 4, 0), cub(2, 3, 0, outside=True)]},
                {"id": 11, "label_id": 3, "shapes": [cub(0, 9, 9)]},                   # QC_SUGGESTION -> bo qua
            ],
        }

    def test_tokens_cats_refs(self):
        job = ca.load_job(self.annotations, LABELS, self.frames)
        toks = [a["token"] for a in job["anns"]]
        self.assertEqual(sorted(toks), ["s77", "t10:0", "t10:1", "t10:3"])           # outside + QC_SUGGESTION bi bo
        self.assertEqual(job["cats"][toks.index("s77")], "human.pedestrian.adult")
        self.assertEqual(job["refs"]["t10:1"]["track_id"], 10)
        self.assertEqual(job["refs"]["s77"]["kind"], "shape")

    def test_prev_next_follow_frame_order(self):
        job = ca.load_job(self.annotations, LABELS, self.frames)
        by = {a["token"]: a for a in job["anns"]}
        self.assertEqual((by["t10:0"]["prev"], by["t10:0"]["next"]), ("", "t10:1"))
        self.assertEqual((by["t10:1"]["prev"], by["t10:1"]["next"]), ("t10:0", "t10:3"))   # nhay qua frame 2 (outside)
        self.assertEqual(by["t10:3"]["next"], "")
        self.assertEqual((by["s77"]["prev"], by["s77"]["next"]), ("", ""))

    def test_prev_next_when_shapes_listed_out_of_order(self):
        """CVAT khong dam bao thu tu shape trong track -> phai sap theo frame."""
        ann = {"shapes": [], "tracks": [{"id": 3, "label_id": 1, "shapes": [cub(2, 3, 0), cub(0, 1, 0), cub(1, 2, 0)]}]}
        job = ca.load_job(ann, LABELS, self.frames)
        by = {a["token"]: a for a in job["anns"]}
        self.assertEqual((by["t3:0"]["prev"], by["t3:0"]["next"]), ("", "t3:1"))
        self.assertEqual((by["t3:1"]["prev"], by["t3:1"]["next"]), ("t3:0", "t3:2"))
        self.assertEqual((by["t3:2"]["prev"], by["t3:2"]["next"]), ("t3:1", ""))

    def test_global_view_uses_ego_pose(self):
        job = ca.load_job(self.annotations, LABELS, self.frames)
        g = {a["token"]: a for a in job["anns_global"]}
        self.assertAlmostEqual(g["t10:3"]["translation"][0], 300 + 4, places=9)       # ego frame 3 o x = 300
        self.assertEqual(job["sample_ts"]["s3"], 1500000)

    def test_no_ego_disables_global(self):
        job = ca.load_job(self.annotations, LABELS, [{"sample_token": "a"}] * 4)
        self.assertIsNone(job["anns_global"])

    def test_occlusion_and_distance(self):
        ann = {"shapes": [cub(0, 3, 4, id=1, label_id=1, occluded=True)], "tracks": []}
        job = ca.load_job(ann, LABELS, [])
        self.assertEqual(job["anns"][0]["visibility_token"], "occ")
        self.assertEqual(job["vis"]["occ"], "v0-40")
        self.assertAlmostEqual(job["dist"][job["anns"][0]["token"]], 5.0)

    def test_roundtrip_through_analysis_heading(self):
        """Xe chay +x 5 m/s nhung yaw ghi nguoc -> HEADING_REVERSED qua ca duong CVAT -> qc.analyze."""
        frames = [{"sample_token": "s%d" % i, "timestamp": i * 500000, "ego_translation": [0, 0, 0],
                   "ego_rotation": ca.quat_from_yaw(0.0)} for i in range(3)]
        ann = {"shapes": [], "tracks": [{"id": 1, "label_id": 1, "shapes": [
            cub(i, 2.5 * i, 0, rz=math.pi) for i in range(3)]}]}
        job = ca.load_job(ann, LABELS, frames)
        rows, _ = qc.analyze(job["anns"], job["cats"], job["vis"], dist=job["dist"], sample_ts=job["sample_ts"],
                             anns_motion=job["anns_global"], ranges={}, expect={})
        issues = {r[3] for r in rows}
        self.assertIn("HEADING_REVERSED", issues)


if __name__ == "__main__":
    unittest.main()

"""Unit test cho cuboid-qc. Chay:  python -m unittest discover -s tests -v   (tu thu muc cuboid-qc)

Dap an hinh hoc deu tinh tay (khong lay tu chinh code), de bat loi that thay vi chi 'chay khong crash'.
"""
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cuboidqc.core import qc as qc  # noqa: E402

try:
    import numpy as np
    from cuboidqc.core import boxfit as boxfit
except ImportError:      # test boxfit bi bo qua neu khong co numpy
    np = None
    boxfit = None

from cuboidqc.core import fixes as fixes  # noqa: E402


def quat(yaw):
    return [math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)]


def box(x=0.0, y=0.0, z=0.0, w=2.0, l=4.0, h=2.0, yaw=0.0, token="t", sample="s", pts=100, **kw):
    a = {"token": token, "sample_token": sample, "translation": [x, y, z], "size": [w, l, h],
         "rotation": quat(yaw), "num_lidar_pts": pts, "prev": "", "next": "", "instance_token": "i_" + token,
         "visibility_token": "4"}
    a.update(kw)
    return a


class TestGeometry(unittest.TestCase):
    def test_yaw_roundtrip(self):
        for deg in (0, 30, 90, 135, 179, -45, -120):
            yaw = math.radians(deg)
            self.assertAlmostEqual(qc.yaw_of(quat(yaw)), yaw, places=9, msg="deg=%d" % deg)

    def test_yaw_with_roll_pitch_matches_rotation_matrix(self):
        """Quaternion tong quat (co roll/pitch): yaw phai khop yaw tinh doc lap tu ma tran quay."""
        from cuboidqc.core import lidar as lidar

        def qmul(a, b):
            w1, x1, y1, z1 = a
            w2, x2, y2, z2 = b
            return [w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                    w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2]
        for yaw, roll, pitch in ((0.7, 0.2, -0.1), (-2.0, 0.3, 0.25), (3.0, -0.15, 0.1)):
            qz = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
            qy = [math.cos(pitch / 2), 0, math.sin(pitch / 2), 0]
            qx = [math.cos(roll / 2), math.sin(roll / 2), 0, 0]
            q = qmul(qz, qmul(qy, qx))                       # R = Rz(yaw) Ry(pitch) Rx(roll)
            R = lidar.quat_to_mat(q)
            expected = math.atan2(R[1][0], R[0][0])
            self.assertAlmostEqual(qc.yaw_of(q), expected, places=9)
            self.assertAlmostEqual(qc.yaw_of(q), yaw, places=9)

    def test_bev_corners_axis_aligned(self):
        pts = qc.bev_corners(box(w=2, l=4, yaw=0))
        xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
        self.assertEqual((xs[0], xs[-1], ys[0], ys[-1]), (-2, 2, -1, 1))

    def test_bev_corners_yaw_90(self):
        pts = qc.bev_corners(box(w=2, l=4, yaw=math.pi / 2))     # chieu dai doc theo truc y
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        self.assertAlmostEqual(max(xs) - min(xs), 2, places=9)
        self.assertAlmostEqual(max(ys) - min(ys), 4, places=9)

    def test_polygon_orientation_is_ccw(self):
        self.assertGreater(qc.poly_area(qc.bev_corners(box(yaw=0.7))), 0)

    def test_clip_octagon(self):
        sq = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        c, s = math.cos(math.pi / 4), math.sin(math.pi / 4)
        rot = [(x * c - y * s, x * s + y * c) for x, y in sq]
        area = abs(qc.poly_area(qc.clip_poly(sq, rot)))
        self.assertAlmostEqual(area, 2 * (math.sqrt(2) - 1) * 4, places=9)   # bat giac deu 3.3137

    def test_clip_disjoint_is_empty(self):
        a = [(0, 0), (1, 0), (1, 1), (0, 1)]
        b = [(5, 5), (6, 5), (6, 6), (5, 6)]
        self.assertEqual(len(qc.clip_poly(a, b)), 0)

    def test_overlap_identical(self):
        iou, cont = qc.overlap_3d(box(), box())
        self.assertAlmostEqual(iou, 1.0, places=9)
        self.assertAlmostEqual(cont, 1.0, places=9)

    def test_overlap_disjoint(self):
        self.assertEqual(qc.overlap_3d(box(), box(x=10)), (0.0, 0.0))

    def test_overlap_half_shift_xy(self):
        iou, cont = qc.overlap_3d(box(l=4), box(x=2, l=4))        # chong 1 nua: inter = V/2, union = 1.5V
        self.assertAlmostEqual(iou, 1 / 3, places=9)
        self.assertAlmostEqual(cont, 0.5, places=9)

    def test_overlap_half_shift_z(self):
        iou, _ = qc.overlap_3d(box(h=2), box(z=1, h=2))
        self.assertAlmostEqual(iou, 1 / 3, places=9)

    def test_overlap_no_z_overlap(self):
        self.assertEqual(qc.overlap_3d(box(h=2), box(z=2.5, h=2)), (0.0, 0.0))

    def test_overlap_contained(self):
        big, small = box(w=4, l=8, h=4), box(w=1, l=2, h=1)
        iou, cont = qc.overlap_3d(big, small)
        self.assertAlmostEqual(iou, (1 * 2 * 1) / (4 * 8 * 4), places=9)
        self.assertAlmostEqual(cont, 1.0, places=9)

    def test_overlap_rotated_symmetry(self):
        a, b = box(yaw=0.4), box(x=0.5, yaw=1.1)
        self.assertAlmostEqual(qc.overlap_3d(a, b)[0], qc.overlap_3d(b, a)[0], places=9)

    def test_angle_diff_wraps(self):
        self.assertAlmostEqual(qc.angle_diff(math.radians(179), math.radians(-179)), math.radians(2), places=9)
        self.assertAlmostEqual(qc.angle_diff(0, math.pi), math.pi, places=9)

    def test_percentile(self):
        v = [1, 2, 3, 4, 5]
        self.assertEqual(qc.percentile(v, 0), 1)
        self.assertEqual(qc.percentile(v, 50), 3)
        self.assertEqual(qc.percentile(v, 100), 5)
        self.assertAlmostEqual(qc.percentile(v, 25), 2)


class TestSize(unittest.TestCase):
    def test_prior_when_few_samples(self):
        rows = [("movable_object.trafficcone", 0.4, 0.4, 0.8)] * 5
        ranges = qc.build_size_ranges(rows)
        self.assertEqual(ranges["movable_object.trafficcone"][1], "prior")
        self.assertEqual(qc.check_size("movable_object.trafficcone", (0.4, 0.4, 0.8), ranges), [])
        sev = [s for s, _ in qc.check_size("movable_object.trafficcone", (1.5, 1.5, 3.0), ranges)]
        self.assertEqual(sev, ["ERROR"] * 3)

    def test_data_percentiles_flag_outlier_only(self):
        rows = [("vehicle.car", 1.9 + 0.001 * i, 4.5 + 0.002 * i, 1.7) for i in range(100)]
        ranges = qc.build_size_ranges(rows)
        self.assertTrue(ranges["vehicle.car"][1].startswith("data"))
        self.assertEqual(qc.check_size("vehicle.car", (1.95, 4.6, 1.7), ranges), [])
        res = qc.check_size("vehicle.car", (1.95, 12.0, 1.7), ranges)
        self.assertEqual([s for s, _ in res], ["ERROR"])
        self.assertIn("l=12.00", res[0][1])

    def test_mild_outlier_is_warning(self):
        rows = [("vehicle.car", 1.9, 4.5 + 0.01 * (i % 20), 1.7) for i in range(100)]
        ranges = qc.build_size_ranges(rows)
        hi = ranges["vehicle.car"][0][1][1]
        res = qc.check_size("vehicle.car", (1.9, hi * 1.1, 1.7), ranges)
        self.assertEqual([s for s, _ in res], ["WARNING"])

    def test_unknown_category_ignored(self):
        self.assertEqual(qc.check_size("foo.bar", (1, 1, 1), {}), [])


class TestLidar(unittest.TestCase):
    def setUp(self):
        self.expect = {("vehicle.car", 1): (100.0, 50, "class")}
        self.vis = {"1": "v0-40", "2": "v40-60", "3": "v60-80", "4": "v80-100"}

    def run_check(self, pts, vis="4", d=15.0, cat="vehicle.car", expect=None):
        a = box(pts=pts, visibility_token=vis, token="x")
        dist = {"x": d} if d is not None else {}
        return qc.check_lidar(a, cat, dist, self.vis, self.expect if expect is None else expect)

    def test_ok(self):
        self.assertIsNone(self.run_check(60))

    def test_zero_points_visible_is_error(self):
        self.assertEqual(self.run_check(0)[0], "ERROR")

    def test_below_fraction_is_error(self):
        self.assertEqual(self.run_check(19)[0], "ERROR")     # nguong = 0.2 * 100 = 20
        self.assertIsNone(self.run_check(20))

    def test_medium_visibility_is_warning(self):
        self.assertEqual(self.run_check(5, vis="2")[0], "WARNING")

    def test_heavily_occluded_is_info(self):
        self.assertEqual(self.run_check(0, vis="1")[0], "INFO")

    def test_low_expected_median_is_skipped(self):
        self.assertIsNone(self.run_check(0, expect={("vehicle.car", 1): (3.0, 50, "class")}))

    def test_group_fallback(self):
        expect = {("vehicle*", 1): (100.0, 50, "nhom")}
        self.assertEqual(self.run_check(1, expect=expect)[0], "ERROR")

    def test_fixed_threshold_without_distance(self):
        self.assertEqual(self.run_check(2, d=None)[0], "ERROR")     # vehicle: nguong co dinh 5
        self.assertIsNone(self.run_check(5, d=None))

    def test_dist_bin(self):
        self.assertEqual([qc.dist_bin(d) for d in (0, 9.99, 10, 49.9, 50, 120)], [0, 0, 1, 4, 5, 5])


class TestOverlap(unittest.TestCase):
    def cats(self, *c):
        return list(c)

    def test_same_class_overlap_flagged(self):
        res = qc.check_overlap([box(token="a"), box(x=1, token="b")], ["vehicle.car", "vehicle.car"])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][4], "ERROR")         # IoU 3D = 3/5 = 0.6

    def test_far_apart_not_flagged(self):
        self.assertEqual(qc.check_overlap([box(token="a"), box(x=30, token="b")], ["vehicle.car"] * 2), [])

    def test_other_sample_not_compared(self):
        self.assertEqual(qc.check_overlap([box(token="a", sample="s1"), box(token="b", sample="s2")],
                                          ["vehicle.car"] * 2), [])

    def test_bicycle_with_rider_allowed(self):
        a = box(token="a", w=0.6, l=1.8, h=1.2)
        b = box(token="b", w=0.6, l=0.6, h=1.8)
        self.assertEqual(qc.check_overlap([a, b], ["vehicle.bicycle", "human.pedestrian.adult"]), [])

    def test_two_pedestrians_slight_overlap_suppressed(self):
        a, b = box(token="a", w=.6, l=.6, h=1.7), box(token="b", x=0.5, w=.6, l=.6, h=1.7)   # IoU ~ 0.09
        self.assertEqual(qc.check_overlap([a, b], ["human.pedestrian.adult"] * 2), [])

    def test_two_pedestrians_heavy_overlap_flagged(self):
        a, b = box(token="a", w=.6, l=.6, h=1.7), box(token="b", x=0.1, w=.6, l=.6, h=1.7)
        self.assertEqual(len(qc.check_overlap([a, b], ["human.pedestrian.adult"] * 2)), 1)

    def test_barriers_in_row_allowed(self):
        self.assertEqual(qc.check_overlap([box(token="a"), box(token="b", x=1)],
                                          ["movable_object.barrier"] * 2), [])

    def test_containment_flagged(self):
        big, small = box(token="a", w=4, l=8, h=4), box(token="b", w=1, l=2, h=1)
        res = qc.check_overlap([big, small], ["vehicle.truck", "vehicle.car"])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][4], "ERROR")          # chua 100%


class TestHeading(unittest.TestCase):
    def chain(self, yaw, speed, n=3, cat="vehicle.car"):
        anns = []
        for i in range(n):
            anns.append(box(x=i * speed * 0.5, token="a%d" % i, sample="s%d" % i, yaw=yaw,
                            prev="a%d" % (i - 1) if i else "", next="a%d" % (i + 1) if i < n - 1 else ""))
        ts = {"s%d" % i: i * 500000 for i in range(n)}     # 0.5 s moi frame
        return anns, [cat] * n, ts

    def test_forward_ok(self):
        self.assertEqual(qc.check_heading(*self.chain(0.0, 5.0)), [])

    def test_reversed_flagged_error(self):
        res = qc.check_heading(*self.chain(math.pi, 5.0))
        self.assertEqual(len(res), 3)
        self.assertTrue(all(r[2] == "ERROR" for r in res))
        self.assertAlmostEqual(res[0][3], 180.0, places=6)

    def test_slow_reversed_is_warning(self):
        res = qc.check_heading(*self.chain(math.pi, 2.0))
        self.assertTrue(res and all(r[2] == "WARNING" for r in res))

    def test_parked_ignored(self):
        self.assertEqual(qc.check_heading(*self.chain(math.pi, 0.5)), [])

    def test_sideways_not_flagged(self):
        self.assertEqual(qc.check_heading(*self.chain(math.pi / 2, 5.0)), [])

    def test_pedestrian_ignored(self):
        self.assertEqual(qc.check_heading(*self.chain(math.pi, 5.0, cat="human.pedestrian.adult")), [])

    def test_threshold_boundary(self):
        just_under = math.radians(qc.HEADING_FLIP_DEG - 2)
        just_over = math.radians(qc.HEADING_FLIP_DEG + 2)
        self.assertEqual(qc.check_heading(*self.chain(just_under, 5.0)), [])
        self.assertEqual(len(qc.check_heading(*self.chain(just_over, 5.0))), 3)


class TestFixes(unittest.TestCase):
    def test_flip_yaw(self):
        a = box(yaw=0.3)
        f = fixes.fix_heading(a, 178.0, vel_yaw=0.3 + math.pi)
        self.assertEqual(f["kind"], "flip_yaw")
        self.assertAlmostEqual(qc.angle_diff(f["box"]["yaw"], 0.3 + math.pi), 0, places=9)

    def test_align_yaw_when_not_180(self):
        f = fixes.fix_heading(box(yaw=0.0), 130.0, vel_yaw=2.0)
        self.assertEqual(f["kind"], "align_yaw")
        self.assertAlmostEqual(f["box"]["yaw"], 2.0)

    def test_apply_fix_keeps_everything_else(self):
        a = box(yaw=0.0, token="k")
        f = {"kind": "resize", "box": {"translation": [1, 2, 3], "size": [1, 2, 3], "yaw": 0.5}}
        b = fixes.apply_fix(a, f)
        self.assertEqual(b["translation"], [1, 2, 3])
        self.assertAlmostEqual(qc.yaw_of(b["rotation"]), 0.5)
        self.assertEqual(b["token"], "k")
        self.assertEqual(a["translation"], [0.0, 0.0, 0.0])      # ban goc khong bi doi
        self.assertIsNone(fixes.apply_fix(a, {"kind": "delete", "box": None}))

    def test_fix_size_only_changes_bad_dims(self):
        rows = [("vehicle.car", 1.9, 4.5 + 0.01 * (i % 20), 1.7) for i in range(100)]
        ranges = qc.build_size_ranges(rows)
        med = {"vehicle.car": [1.9, 4.6, 1.7]}
        f = fixes.fix_size(box(w=1.9, l=12.0, h=1.7), "vehicle.car", ranges, med)
        self.assertEqual(f["box"]["size"], [1.9, 4.6, 1.7])
        self.assertIsNone(fixes.fix_size(box(w=1.9, l=4.6, h=1.7), "vehicle.car", ranges, med))

    def test_duplicate_deletes_fewer_points_box(self):
        a, b = box(token="a", pts=10), box(token="b", pts=50)
        fa = fixes.fix_overlap(a, b, "vehicle.car", "vehicle.car", 0.9, 0.95)
        fb = fixes.fix_overlap(b, a, "vehicle.car", "vehicle.car", 0.9, 0.95)
        self.assertEqual(fa["kind"], "delete")
        self.assertEqual(fa["delete"], "a")
        self.assertEqual(fb["kind"], "review")        # box nhieu diem hon: giu lai

    def test_overlap_different_class_only_review(self):
        f = fixes.fix_overlap(box(token="a"), box(token="b"), "human.pedestrian.adult", "vehicle.truck", 0.01, 1.0)
        self.assertEqual(f["kind"], "review")


@unittest.skipIf(np is None, "can numpy")
class TestBoxFit(unittest.TestCase):
    @staticmethod
    def cloud(rng, center, size, yaw, n, extra=None):
        """n diem phan bo deu trong box (de chuc mat tren be mat), cong them diem nhieu."""
        w, l, h = size
        u = rng.uniform(-l / 2, l / 2, n)
        v = rng.uniform(-w / 2, w / 2, n)
        z = rng.uniform(-h / 2 + 0.2, h / 2, n)
        c, s = math.cos(yaw), math.sin(yaw)
        P = np.stack([center[0] + u * c - v * s, center[1] + u * s + v * c, center[2] + z], axis=1)
        return P if extra is None else np.vstack([P, extra])

    def setUp(self):
        self.rng = np.random.default_rng(0)

    def test_correct_box_not_flagged(self):
        P = self.cloud(self.rng, (0, 0, 0), (2, 4, 2), 0.0, 300)
        res = boxfit.fit_box(box(), P)
        self.assertIsNone(boxfit.judge(res))

    def test_shifted_along_length_is_warning(self):
        # dich 1.25 m doc theo chieu dai 4 m: box van chua ~69% diem -> chi WARNING (khong ERROR)
        P = self.cloud(self.rng, (1.25, 0.0, 0.0), (2, 4, 2), 0.0, 300)
        res = boxfit.fit_box(box(), P)
        self.assertEqual(boxfit.judge(res), "WARNING")
        self.assertAlmostEqual(res["box"]["translation"][0], 1.25, delta=0.26)

    def test_shifted_sideways_is_error_and_recovered(self):
        # dich ngang 1.5 m (be rong 2 m): box chi con ~25% diem -> ERROR
        P = self.cloud(self.rng, (0.0, 1.5, 0.0), (2, 4, 2), 0.0, 300)
        res = boxfit.fit_box(box(), P)
        self.assertEqual(boxfit.judge(res), "ERROR")
        self.assertAlmostEqual(res["box"]["translation"][1], 1.5, delta=0.26)
        self.assertGreater(res["best"], 2 * res["cur"])

    def test_shift_below_min_not_flagged(self):
        P = self.cloud(self.rng, (0.0, 0.25, 0.0), (2, 4, 2), 0.0, 300)     # lech 0.25 m < FIT_MIN_SHIFT
        self.assertIsNone(boxfit.judge(boxfit.fit_box(box(), P)))

    def test_rotated_box_shift_in_box_frame(self):
        yaw = math.radians(35)
        true_c = (0.0 + 1.0 * math.cos(yaw), 0.0 + 1.0 * math.sin(yaw), 0.0)     # dich 1 m doc theo huong box
        P = self.cloud(self.rng, true_c, (2, 4, 2), yaw, 300)
        res = boxfit.fit_box(box(yaw=yaw), P)
        t = res["box"]["translation"]
        self.assertAlmostEqual(t[0], true_c[0], delta=0.26)
        self.assertAlmostEqual(t[1], true_c[1], delta=0.26)

    def test_too_few_points_returns_none(self):
        P = self.cloud(self.rng, (0, 0, 0), (2, 4, 2), 0.0, 3)
        self.assertIsNone(boxfit.fit_box(box(), P))

    def test_ground_points_ignored(self):
        # 500 diem mat dat DAY dac ngay canh box (x tu 1.5 den 3.5), cao 0.05 m so voi day box (z = -1)
        # neu khong loc mat dat, dich box sang day se 'chua' them 500 diem va bi bao lech.
        ground = np.stack([self.rng.uniform(1.5, 3.5, 500), self.rng.uniform(-1, 1, 500),
                           np.full(500, -0.95)], axis=1)
        P = self.cloud(self.rng, (0, 0, 0), (2, 4, 2), 0.0, 100, extra=ground)
        self.assertIsNone(boxfit.judge(boxfit.fit_box(box(), P)))

    def test_neighbor_points_excluded_by_owner(self):
        a, nb = box(token="a"), box(token="b", x=3.5)            # box ke ben chua cum diem cua no
        P = self.cloud(self.rng, (3.5, 0, 0), (2, 4, 2), 0.0, 300)
        owner = boxfit.owner_map([a, nb], P)
        self.assertGreater((owner == 1).sum(), 250)
        res = boxfit.fit_box(a, P, owner, 0)
        self.assertIsNone(res)                                    # khong con diem nao de 'chiem'

    def test_wall_is_not_an_object(self):
        """Hang diem thang dai (tuong/le duong) nam sat box: dich box vao do khong phai la 'vat the that'."""
        wall = np.stack([np.linspace(-6, 10, 1600), np.full(1600, 1.6), self.rng.uniform(-0.8, 0.9, 1600)], axis=1)
        P = self.cloud(self.rng, (0, 0, 0), (2, 4, 2), 0.0, 30, extra=wall)      # vat that chi 30 diem, nam dung cho
        res = boxfit.fit_box(box(), P)
        self.assertIsNotNone(res)
        self.assertLess(res["compact"], qc.FIT_MIN_COMPACT)
        self.assertIsNone(boxfit.judge(res))

    def test_compact_object_keeps_high_compactness(self):
        P = self.cloud(self.rng, (0.0, 1.5, 0.0), (2, 4, 2), 0.0, 300)
        res = boxfit.fit_box(box(), P)
        self.assertGreaterEqual(res["compact"], qc.FIT_MIN_COMPACT)
        self.assertEqual(boxfit.judge(res), "ERROR")

    def test_count_in_box(self):
        P = np.array([[0, 0, 0], [1.9, 0.9, 0.9], [2.1, 0, 0], [0, 0, 1.1]], dtype=float)
        self.assertEqual(boxfit.count_in_box(P, box()), 2)


class TestEndToEnd(unittest.TestCase):
    """Chay qc.run tren du lieu gia lap co loi chen san; moi loi phai bi bat, khong co bao nham."""

    def test_synthetic_dataset(self):
        import json
        import subprocess
        here = os.path.join(os.path.dirname(__file__), "..")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.check_call([sys.executable, os.path.join(here, "scripts", "make_synthetic.py"), tmp],
                                  stdout=subprocess.DEVNULL)
            rows = qc.run(tmp, "v1.0-synth", os.path.join(tmp, "r.csv"), quiet=True, use_points=False)
            with open(os.path.join(tmp, "injected.json")) as f:
                injected = json.load(f)
        flagged = {r[1] for r in rows if r[4] in ("ERROR", "WARNING")}
        expected = {t for t, tag in injected.items() if "bi che" not in tag}
        self.assertTrue(expected <= flagged, "bo sot: %s" % (expected - flagged))
        self.assertLessEqual(len(flagged - expected), 2)           # cho phep toi da vai outlier tu nhien
        # box bi che nhieu chi la INFO, khong phai loi
        occluded = [t for t, tag in injected.items() if "bi che" in tag]
        self.assertTrue(all(r[4] == "INFO" for r in rows if r[1] in occluded))

    def test_run_survives_missing_geometry(self):
        """Du lieu khong co translation/rotation/sample_data van chay duoc (chi 2 checker dau)."""
        import subprocess
        here = os.path.join(os.path.dirname(__file__), "..")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.check_call([sys.executable, os.path.join(here, "scripts", "make_synthetic.py"), tmp],
                                  stdout=subprocess.DEVNULL)
            rows = qc.run(tmp, "v1.0-synth", os.path.join(tmp, "r.csv"), quiet=True)   # use_points mac dinh = True
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()

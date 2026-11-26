"""Test cvat_qc: phan tich job + ke hoach ghi nguoc (khong can CVAT that)."""
import json
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cuboidqc.cvat import adapter as ca  # noqa: E402
from cuboidqc.cvat import runner as cq  # noqa: E402

LABELS = {"Car": 1, "Pedestrian": 2, "QC_SUGGESTION": 9}
ATTRS = {("Car", "qc_issue"): 11, ("Car", "qc_note"): 12, ("Pedestrian", "qc_issue"): 21,
         ("Pedestrian", "qc_note"): 22, ("QC_SUGGESTION", "issue"): 91, ("QC_SUGGESTION", "target"): 92,
         ("QC_SUGGESTION", "note"): 93}
ID2LABEL = {v: k for k, v in LABELS.items()}
EMPTY_PROFILE = {"size_ranges": {}, "pts_expect": [], "size_median": {}}


def shape(frame, x, y, yaw=0.0, size=(2.0, 4.0, 1.6), z=0.8, **kw):
    s = {"type": "cuboid", "frame": frame, "points": ca.box_to_points([x, y, z], size, yaw), "occluded": False,
         "outside": False, "z_order": 0, "rotation": 0.0, "attributes": []}
    s.update(kw)
    return s


def cloud(rng, center, size_wlh, yaw, n):
    w, l, h = size_wlh
    u, v = rng.uniform(-l / 2, l / 2, n), rng.uniform(-w / 2, w / 2, n)
    z = rng.uniform(center[2] - h / 2 + 0.25, center[2] + h / 2, n)
    c, s = math.cos(yaw), math.sin(yaw)
    return np.stack([center[0] + u * c - v * s, center[1] + u * s + v * c, z], axis=1)


def frames(n, speed=0.0):
    return [{"sample_token": "s%d" % i, "timestamp": i * 500000, "ego_translation": [speed * 0.5 * i, 0.0, 0.0],
             "ego_rotation": [1.0, 0.0, 0.0, 0.0], "name": "%06d.pcd" % i} for i in range(n)]


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(1)

    def job(self, tracks, shapes=()):
        return {"version": 0, "tags": [], "shapes": list(shapes), "tracks": tracks}

    def test_shifted_box_flagged_with_suggestion_near_truth(self):
        pts = {0: cloud(self.rng, (10, 0, 0.8), (2, 4, 1.6), 0.0, 300)}
        # box ghi lech ngang 1.6 m
        ann = self.job([{"id": 5, "label_id": 1, "frame": 0, "attributes": [], "shapes": [shape(0, 10, 1.6)]}])
        res = cq.analyze_job(ann, ID2LABEL, frames(1), pts, EMPTY_PROFILE)
        fl = cq.summarize(res)
        self.assertEqual(list(fl), ["t5:0"])
        self.assertIn("BOX_OFFSET", fl["t5:0"]["issues"])
        fx = res["sugg"][("t5:0", "BOX_OFFSET")]
        self.assertEqual(fx["kind"], "refit")
        self.assertAlmostEqual(fx["box"]["translation"][1], 0.0, delta=0.26)

    def test_correct_box_not_flagged(self):
        pts = {0: cloud(self.rng, (10, 0, 0.8), (2, 4, 1.6), 0.0, 300)}
        ann = self.job([{"id": 5, "label_id": 1, "frame": 0, "attributes": [], "shapes": [shape(0, 10, 0.0)]}])
        res = cq.analyze_job(ann, ID2LABEL, frames(1), pts, EMPTY_PROFILE)
        self.assertEqual(cq.summarize(res), {})

    def test_reversed_heading_suggestion_in_ego_frame(self):
        """Xe chay +x 5 m/s trong global; ego dung yen. Yaw ghi nguoc -> goi y lat 180, yaw ket qua ~ 0."""
        fr = frames(3)
        shapes = [shape(i, 10 + 2.5 * i, 0.0, yaw=math.pi) for i in range(3)]
        ann = self.job([{"id": 1, "label_id": 1, "frame": 0, "attributes": [], "shapes": shapes}])
        pts = {i: cloud(self.rng, (10 + 2.5 * i, 0, 0.8), (2, 4, 1.6), 0.0, 200) for i in range(3)}
        res = cq.analyze_job(ann, ID2LABEL, fr, pts, EMPTY_PROFILE)
        fx = res["sugg"][("t1:1", "HEADING_REVERSED")]
        self.assertEqual(fx["kind"], "flip_yaw")
        self.assertAlmostEqual(abs(fx["box"]["yaw"]), 0.0, places=6)

    def test_heading_suggestion_accounts_for_ego_rotation(self):
        """Ego quay 90 do: goi y 'align_yaw' phai tinh theo he ego, khong phai he global."""
        fr = frames(3)
        for f in fr:
            f["ego_rotation"] = ca.quat_from_yaw(math.pi / 2)
        # trong ego, xe chay doc +y (toc do 5 m/s) nhung yaw ghi lech 130 do so voi huong chay (khong gan 180)
        yaw = math.pi / 2 + math.radians(130)
        shapes = [shape(i, 5.0, 10 + 2.5 * i, yaw=yaw) for i in range(3)]
        ann = self.job([{"id": 1, "label_id": 1, "frame": 0, "attributes": [], "shapes": shapes}])
        res = cq.analyze_job(ann, ID2LABEL, fr, {i: np.zeros((0, 3)) for i in range(3)}, EMPTY_PROFILE)
        fx = res["sugg"][("t1:1", "HEADING_REVERSED")]
        self.assertEqual(fx["kind"], "align_yaw")
        # xe chay doc +y trong ego (do ego quay, global khac) -> yaw mong muon ~ 90 do trong ego
        self.assertAlmostEqual(fx["box"]["yaw"], math.pi / 2, places=6)

    def test_no_points_still_runs_other_checks(self):
        ann = self.job([{"id": 1, "label_id": 1, "frame": 0, "attributes": [], "shapes": [shape(0, 10, 0)]}])
        res = cq.analyze_job(ann, ID2LABEL, frames(1), lambda i: None, EMPTY_PROFILE)
        self.assertEqual(cq.summarize(res), {})

    def test_summarize_merges_issues_and_takes_worst_severity(self):
        job = {"refs": {"a": {}}}
        res = {"rows": [("s", "a", "c", "BAD_SIZE", "WARNING", "d1"), ("s", "a", "c", "BOX_OFFSET", "ERROR", "d2"),
                        ("s", "b", "c", "LOW_LIDAR_PTS", "INFO", "d3")], "job": job}
        out = cq.summarize(res)
        self.assertEqual(list(out), ["a"])
        self.assertEqual(out["a"]["severity"], "ERROR")
        self.assertEqual(out["a"]["issues"], ["BAD_SIZE", "BOX_OFFSET"])


class TestTrackSizeFix(unittest.TestCase):
    def ann(self, size, token="x"):
        return {"token": token, "translation": [10, 0, 0.8], "size": list(size), "rotation": ca.quat_from_yaw(0.0)}

    def test_median_of_consistent_track(self):
        from cuboidqc.core import fixes as fixes
        others = [self.ann((0.65, 0.7, 1.75)) for _ in range(5)]
        fx = fixes.fix_size_by_track(self.ann((1.1, 1.2, 2.97)), others)
        self.assertEqual(fx["kind"], "resize")
        self.assertEqual(fx["box"]["size"], [0.65, 0.7, 1.75])
        self.assertEqual(fx["box"]["translation"], [10, 0, 0.8])            # chi doi kich thuoc

    def test_too_few_frames_gives_none(self):
        from cuboidqc.core import fixes as fixes
        self.assertIsNone(fixes.fix_size_by_track(self.ann((1.1, 1.2, 2.97)), [self.ann((0.65, 0.7, 1.75))] * 2))

    def test_inconsistent_track_gives_none(self):
        from cuboidqc.core import fixes as fixes
        others = [self.ann((0.5 + 0.3 * i, 0.7, 1.75)) for i in range(5)]      # kich thuoc nhay lung tung
        self.assertIsNone(fixes.fix_size_by_track(self.ann((1.1, 1.2, 2.97)), others))

    def test_tolerates_a_few_outlier_frames(self):
        from cuboidqc.core import fixes as fixes
        others = [self.ann((0.65, 0.7, 1.75)) for _ in range(9)] + [self.ann((1.2, 1.3, 3.0))]
        fx = fixes.fix_size_by_track(self.ann((1.1, 1.2, 2.97)), others)
        self.assertEqual(fx["box"]["size"], [0.65, 0.7, 1.75])

    def test_already_matching_size_gives_none(self):
        from cuboidqc.core import fixes as fixes
        others = [self.ann((0.65, 0.7, 1.75)) for _ in range(5)]
        self.assertIsNone(fixes.fix_size_by_track(self.ann((0.65, 0.7, 1.75)), others))

    def test_analyze_job_prefers_track_median_over_class_median(self):
        """Nguoi di bo ghi x1.7 o 1 frame: goi y phai ve DUNG kich thuoc track, khong phai trung vi class."""
        prof = {"size_ranges": {"human.pedestrian.adult": {"dims": [[0.3, 1.06], [0.3, 1.2], [1.2, 2.1]], "src": "data"}},
                "pts_expect": [], "size_median": {"human.pedestrian.adult": [0.7, 0.8, 1.6]}}
        shapes = [shape(i, 10, i, size=(0.65, 0.7, 1.75)) for i in range(6)]
        shapes[3] = shape(3, 10, 3, size=(1.1, 1.2, 2.97))
        ann = {"version": 0, "tags": [], "shapes": [], "tracks": [{"id": 4, "label_id": 2, "frame": 0, "attributes": [], "shapes": shapes}]}
        res = cq.analyze_job(ann, ID2LABEL, frames(6), lambda i: None, prof)
        fx = res["sugg"][("t4:3", "BAD_SIZE")]
        self.assertEqual(fx["box"]["size"], [0.65, 0.7, 1.75])


class TestVerifyInjected(unittest.TestCase):
    """verify_injected phai phan biet: BAT (con loi va bi co) / DA SUA (box da tro ve box goc) / BO SOT."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.orig = ca.box_to_points([10, 0, 0.8], (2.0, 4.0, 1.6), 0.0)
        bad = ca.box_to_points([10, 1.6, 0.8], (2.0, 4.0, 1.6), 0.0)           # lech ngang 1.6 m
        with open(os.path.join(d, "annotations.json"), "w") as f:
            json.dump({"tracks": [{"key": "k1", "label": "Car", "shapes": [
                {"frame": 0, "points": bad, "occluded": False, "outside": False}]}]}, f)
        with open(os.path.join(d, "injected.json"), "w") as f:
            json.dump([{"kind": "offset_car", "expect_issue": "BOX_OFFSET", "track": "k1", "frame": 0,
                        "original_points": self.orig, "note": ""}], f)
        self.demo = d

    def result_for(self, points, flagged):
        t, size, yaw = ca.points_to_box(points)
        a = {"token": "t1:0", "sample_token": "s0", "translation": t, "size": list(size),
             "rotation": ca.quat_from_yaw(yaw)}
        rows = [("s0", "t1:0", "vehicle.car", "BOX_OFFSET", "ERROR", "x")] if flagged else []
        return {"rows": rows, "sugg": {}, "job": {"anns": [a], "refs": {"t1:0": {"frame": 0, "track_id": 1, "label": "Car"}}}}

    def test_still_wrong_and_flagged_is_caught(self):
        bad = ca.box_to_points([10, 1.6, 0.8], (2.0, 4.0, 1.6), 0.0)
        v = cq.verify_injected(self.demo, self.result_for(bad, True), None)[0]
        self.assertEqual(v["status"], "caught")
        self.assertTrue(v["caught"])

    def test_still_wrong_and_not_flagged_is_missed(self):
        bad = ca.box_to_points([10, 1.6, 0.8], (2.0, 4.0, 1.6), 0.0)
        v = cq.verify_injected(self.demo, self.result_for(bad, False), None)[0]
        self.assertEqual(v["status"], "missed")

    def test_box_back_at_original_is_fixed_not_missed(self):
        v = cq.verify_injected(self.demo, self.result_for(self.orig, False), None)[0]
        self.assertEqual(v["status"], "fixed")
        self.assertGreater(v["iou_now"], 0.95)
        self.assertFalse(v["caught"])

    def test_flipped_original_is_not_counted_as_fixed(self):
        """Box dung vi tri nhung lat 180 do: IoU hinh hoc = 1 nhung KHONG phai 'da sua'."""
        flipped = ca.box_to_points([10, 0, 0.8], (2.0, 4.0, 1.6), math.pi)
        with open(os.path.join(self.demo, "injected.json")) as f:
            inj = json.load(f)
        inj[0].update(kind="heading_flip", expect_issue="HEADING_REVERSED")
        with open(os.path.join(self.demo, "injected.json"), "w") as f:
            json.dump(inj, f)
        with open(os.path.join(self.demo, "annotations.json")) as f:
            ann = json.load(f)
        ann["tracks"][0]["shapes"][0]["points"] = flipped
        with open(os.path.join(self.demo, "annotations.json"), "w") as f:
            json.dump(ann, f)
        v = cq.verify_injected(self.demo, self.result_for(flipped, False), None)[0]
        self.assertEqual(v["status"], "missed")


class TestCollateral(unittest.TestCase):
    """collateral_changes: box KHONG phai loi chen nhung da bi apply doi di (nguy co cua co nham)."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.demo = self.tmp.name
        pts = lambda x, y: ca.box_to_points([x, y, 0.8], (2.0, 4.0, 1.6), 0.0)
        tracks = [
            {"key": "a", "label": "Car", "shapes": [{"frame": 0, "points": pts(10, 0), "outside": False, "occluded": False}]},
            {"key": "b", "label": "Car", "shapes": [{"frame": 0, "points": pts(20, 0), "outside": False, "occluded": False}]},
            {"key": "c", "label": "Car", "shapes": [{"frame": 0, "points": pts(30, 0), "outside": False, "occluded": False}]},
            {"key": "inj", "label": "Car", "shapes": [{"frame": 0, "points": pts(40, 3), "outside": False, "occluded": False}]},
        ]
        with open(os.path.join(self.demo, "annotations.json"), "w") as f:
            json.dump({"tracks": tracks}, f)
        with open(os.path.join(self.demo, "injected.json"), "w") as f:
            json.dump([{"kind": "offset_car", "expect_issue": "BOX_OFFSET", "track": "inj", "frame": 0,
                        "original_points": pts(40, 0), "note": ""}], f)
        self.pts = pts

    def result(self, current):
        anns, refs = [], {}
        for i, (x, y) in enumerate(current):
            t, size, yaw = ca.points_to_box(self.pts(x, y))
            tok = "t%d:0" % i
            anns.append({"token": tok, "translation": t, "size": list(size), "rotation": ca.quat_from_yaw(yaw)})
            refs[tok] = {"frame": 0, "track_id": i, "label": "Car"}
        return {"job": {"anns": anns, "refs": refs}}

    def test_unchanged_boxes_report_nothing(self):
        r = cq.collateral_changes(self.demo, self.result([(10, 0), (20, 0), (30, 0), (40, 3)]))
        self.assertEqual((r["n"], len(r["changed"]), r["missing"]), (3, 0, 0))

    def test_moved_good_box_is_counted_with_iou(self):
        r = cq.collateral_changes(self.demo, self.result([(10, 0), (20, 1.0), (30, 0), (40, 0)]))
        self.assertEqual([c["key"] for c in r["changed"]], ["b"])
        self.assertLess(r["changed"][0]["iou"], 0.7)              # dich ngang 1 m tren be rong 2 m -> IoU 1/3

    def test_injected_box_changes_are_not_collateral(self):
        r = cq.collateral_changes(self.demo, self.result([(10, 0), (20, 0), (30, 0), (40, 0)]))   # box chen loi da duoc sua
        self.assertEqual(len(r["changed"]), 0)

    def test_deleted_good_box_counts_as_missing(self):
        r = cq.collateral_changes(self.demo, self.result([(10, 0), (30, 0), (40, 3)]))
        self.assertEqual(r["missing"], 1)


class TestWriteback(unittest.TestCase):
    def setUp(self):
        self.fix_box = {"translation": [10.0, 0.0, 0.8], "size": [2.0, 4.0, 1.6], "yaw": 0.0}
        self.annotations = {
            "version": 0, "tags": [],
            "tracks": [
                {"id": 5, "label_id": 1, "frame": 0, "attributes": [], "shapes": [shape(0, 10, 1.6), shape(1, 11, 0)]},
                {"id": 6, "label_id": 1, "frame": 0, "attributes": [], "shapes": [shape(0, 30, 0)]},
            ],
            "shapes": [shape(3, 5, 5, id=77, label_id=9, attributes=[{"spec_id": 91, "value": "old"}])],
        }
        self.annotations["shapes"][0]["label_id"] = 9
        refs = {"t5:0": {"frame": 0, "track_id": 5, "label": "Car"}, "t5:1": {"frame": 1, "track_id": 5, "label": "Car"},
                "t6:0": {"frame": 0, "track_id": 6, "label": "Car"}}
        self.result = {
            "rows": [("s0", "t5:0", "vehicle.car", "BOX_OFFSET", "ERROR", "dich 1.6 m")],
            "sugg": {("t5:0", "BOX_OFFSET"): {"kind": "refit", "box": self.fix_box, "text": "Dich box 1.6 m"}},
            "job": {"refs": refs, "anns": []},
        }

    def attr(self, shape_, spec):
        return next((a["value"] for a in shape_["attributes"] if a["spec_id"] == spec), None)

    def test_only_flagged_track_is_updated(self):
        plan = cq.plan_writeback(self.annotations, self.result, LABELS, ATTRS)
        self.assertEqual([t["id"] for t in plan["update"]["tracks"]], [5])
        s0 = plan["update"]["tracks"][0]["shapes"][0]
        self.assertEqual(self.attr(s0, 11), "ERROR BOX_OFFSET")
        self.assertIn("dich 1.6 m", self.attr(s0, 12))
        s1 = plan["update"]["tracks"][0]["shapes"][1]
        self.assertEqual(s1["attributes"], [])                          # shape khong co khong bi dong vao

    def test_input_not_mutated(self):
        before = json.dumps(self.annotations, sort_keys=True)
        cq.plan_writeback(self.annotations, self.result, LABELS, ATTRS)
        self.assertEqual(json.dumps(self.annotations, sort_keys=True), before)

    def test_suggestion_shape_created_at_fix_box(self):
        plan = cq.plan_writeback(self.annotations, self.result, LABELS, ATTRS)
        self.assertEqual(len(plan["create"]["shapes"]), 1)
        sug = plan["create"]["shapes"][0]
        self.assertEqual((sug["label_id"], sug["frame"], sug["type"]), (9, 0, "cuboid"))
        self.assertEqual(sug["points"][:3], [10.0, 0.0, 0.8])
        self.assertEqual(self.attr(sug, 92), "t5:0")                     # target
        self.assertEqual(self.attr(sug, 91), "BOX_OFFSET")

    def test_old_suggestions_deleted_and_not_flagged_as_targets(self):
        plan = cq.plan_writeback(self.annotations, self.result, LABELS, ATTRS)
        self.assertEqual([s["id"] for s in plan["delete"]["shapes"]], [77])

    def test_rerun_after_fix_clears_attributes(self):
        """Lan chay sau khi het loi: attribute QC cu phai bi xoa (de trong), khong de co ton."""
        first = cq.plan_writeback(self.annotations, self.result, LABELS, ATTRS)
        ann2 = {"version": 0, "tags": [], "shapes": [], "tracks": first["update"]["tracks"] + [self.annotations["tracks"][1]]}
        clean = {"rows": [], "sugg": {}, "job": self.result["job"]}
        plan = cq.plan_writeback(ann2, clean, LABELS, ATTRS)
        self.assertEqual([t["id"] for t in plan["update"]["tracks"]], [5])
        self.assertEqual(self.attr(plan["update"]["tracks"][0]["shapes"][0], 11), "")
        self.assertEqual(plan["create"]["shapes"], [])

    def test_clean_job_touches_nothing(self):
        clean = {"rows": [], "sugg": {}, "job": self.result["job"]}
        plan = cq.plan_writeback({"tracks": self.annotations["tracks"], "shapes": [], "tags": []}, clean, LABELS, ATTRS)
        self.assertTrue(cq._empty(plan["update"]) and cq._empty(plan["create"]) and cq._empty(plan["delete"]))

    def test_apply_replaces_points_and_clears_flag(self):
        plan = cq.plan_writeback(self.annotations, self.result, LABELS, ATTRS, apply=True, apply_policy="all")
        t = plan["update"]["tracks"][0]
        self.assertEqual(t["shapes"][0]["points"][:3], [10.0, 0.0, 0.8])
        self.assertEqual(self.attr(t["shapes"][0], 11), "")
        self.assertEqual(plan["create"]["shapes"], [])
        self.assertEqual(plan["stats"]["applied"], 1)

    def policy_setup(self, kind, severity, issue, basis=None):
        """Track 5 gom 5 frame; frame 2 bi co `issue` kem goi y (kind) co box."""
        shapes = [shape(i, 10, 0) for i in range(5)]
        ann = {"version": 0, "tags": [], "shapes": [],
               "tracks": [{"id": 5, "label_id": 1, "frame": 0, "attributes": [], "shapes": shapes}]}
        refs = {"t5:%d" % i: {"frame": i, "track_id": 5, "label": "Car"} for i in range(5)}
        fx = {"kind": kind, "box": dict(self.fix_box), "text": "sua"}
        if basis:
            fx["basis"] = basis
        res = {"rows": [("s", "t5:2", "vehicle.car", issue, severity, "x")], "sugg": {("t5:2", issue): fx},
               "job": {"refs": refs, "anns": []}}
        return ann, res

    def applied(self, kind, severity, issue, policy, basis=None):
        ann, res = self.policy_setup(kind, severity, issue, basis)
        return cq.plan_writeback(ann, res, LABELS, ATTRS, apply=True, apply_policy=policy)["stats"]

    def test_conservative_applies_flip_only_for_error(self):
        self.assertEqual(self.applied("flip_yaw", "ERROR", "HEADING_REVERSED", "conservative")["applied"], 1)
        s = self.applied("flip_yaw", "WARNING", "HEADING_REVERSED", "conservative")      # xe cham, co the dang lui
        self.assertEqual((s["applied"], s["skipped"]), (0, 1))

    def test_conservative_applies_track_resize_but_not_class_resize(self):
        self.assertEqual(self.applied("resize", "WARNING", "BAD_SIZE", "conservative", basis="track")["applied"], 1)
        s = self.applied("resize", "WARNING", "BAD_SIZE", "conservative", basis="class")
        self.assertEqual((s["applied"], s["skipped"]), (0, 1))

    def test_conservative_never_applies_refit(self):
        for sev in ("ERROR", "WARNING"):
            s = self.applied("refit", sev, "BOX_OFFSET", "conservative")
            self.assertEqual((s["applied"], s["skipped"]), (0, 1))

    def test_all_policy_applies_everything_with_a_box(self):
        self.assertEqual(self.applied("refit", "WARNING", "BOX_OFFSET", "all")["applied"], 1)
        self.assertEqual(self.applied("resize", "WARNING", "BAD_SIZE", "all", basis="class")["applied"], 1)
        self.assertEqual(self.applied("flip_yaw", "WARNING", "HEADING_REVERSED", "all")["applied"], 1)

    def test_skipped_fix_keeps_flag_for_human(self):
        """Goi y bi chan khong tu ap dung thi box van giu co qc_issue de nguoi duyet."""
        ann, res = self.policy_setup("refit", "ERROR", "BOX_OFFSET")
        plan = cq.plan_writeback(ann, res, LABELS, ATTRS, apply=True, apply_policy="conservative")
        shape2 = next(s for t in plan["update"]["tracks"] for s in t["shapes"] if s["frame"] == 2)
        self.assertEqual(self.attr(shape2, 11), "ERROR BOX_OFFSET")
        self.assertEqual(shape2["points"], ann["tracks"][0]["shapes"][2]["points"])       # chua bi doi

    def test_apply_delete_removes_single_shape_track(self):
        anns = {"version": 0, "tags": [], "shapes": [], "tracks": [
            {"id": 8, "label_id": 1, "frame": 4, "attributes": [], "shapes": [shape(4, 10, 0), shape(5, 10, 0, outside=True)]}]}
        res = {"rows": [("s4", "t8:4", "vehicle.car", "OVERLAP", "ERROR", "trung")],
               "sugg": {("t8:4", "OVERLAP"): {"kind": "delete", "delete": "t8:4", "box": None, "text": "xoa"}},
               "job": {"refs": {"t8:4": {"frame": 4, "track_id": 8, "label": "Car"}}, "anns": []}}
        plan = cq.plan_writeback(anns, res, LABELS, ATTRS, apply=True)
        self.assertEqual([t["id"] for t in plan["delete"]["tracks"]], [8])
        self.assertEqual(plan["update"]["tracks"], [])


if __name__ == "__main__":
    unittest.main()

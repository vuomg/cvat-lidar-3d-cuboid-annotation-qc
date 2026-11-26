#!/usr/bin/env python3
"""Chay QC tren mot job CVAT 3D va ghi ket qua NGUOC vao chinh job do (de annotator thay trong CVAT).

Voi moi cuboid bi co:
  - dat attribute  qc_issue / qc_note  tren chinh cuboid (loc duoc bang bo loc cua CVAT)
  - tao them mot cuboid label QC_SUGGESTION (mau xanh) tai vi tri / huong / kich thuoc duoc goi y
Chay lai se xoa cac QC_SUGGESTION cu va cap nhat lai attribute. Voi --apply: ap dung goi y vao cuboid goc.

  python -m cuboidqc.cvat.runner --demo demo_data --profile profile.json            # chay + ghi co vao CVAT
  python -m cuboidqc.cvat.runner --demo demo_data --profile profile.json --apply    # ap dung cac goi y tu dong sua
  python -m cuboidqc.cvat.runner --demo demo_data --profile profile.json --dry-run  # chi bao cao, khong ghi CVAT
"""
import argparse
import copy
import csv
import json
import math
import os

import numpy as np
from cuboidqc import paths

from cuboidqc.core import boxfit as boxfit
from cuboidqc.cvat import adapter as ca
from cuboidqc.cvat import demo as cvat_demo
from cuboidqc.core import fixes as fixes
from cuboidqc.core import qc as qc
from cuboidqc.core import qcprofile as qcprofile
from cuboidqc.cvat.client import Client

SEV_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}
SUGGEST_LABEL = "QC_SUGGESTION"
AUTO_KINDS = ("resize", "flip_yaw", "align_yaw", "refit")     # goi y co box -> co the ap dung tu dong
FIXED_IOU = 0.7          # box loi da duoc coi la 'sua xong' neu IoU 3D co huong voi box goc >= 0.7


# ------------------------------------------------------------------ phan tich (thuan, khong can CVAT)
def analyze_job(annotations, labels_by_id, frames, points_by_frame, profile):
    """Chay toan bo checker tren annotation cua mot job.

    points_by_frame : {frame_index: mang Nx3 (he ego)} hoac callable(frame_index)
    profile         : dict / duong dan profile.json (qcprofile)
    Tra dict: rows, sugg ({(token, issue): fix, da doi sang he ego}), job (ket qua cvat_adapter.load_job)
    """
    job = ca.load_job(annotations, labels_by_id, frames)
    ranges, expect, medians = qcprofile.load(profile)
    frame_of = {f.get("sample_token", "frame%d" % i): i for i, f in enumerate(frames)}
    get_pts = points_by_frame if callable(points_by_frame) else points_by_frame.get
    cache = {}

    def points_fn(sample_token):
        i = frame_of.get(sample_token)
        if i is None:
            return None
        if i not in cache:
            cache[i] = get_pts(i)
        return cache[i]

    for a in job["anns"]:                       # so diem LiDAR that trong tung box (he ego)
        P = points_fn(a["sample_token"])
        if P is not None:
            a["num_lidar_pts"] = boxfit.count_in_box(P, a)
    rows, ctx = qc.analyze(job["anns"], job["cats"], job["vis"], dist=job["dist"], sample_ts=job["sample_ts"],
                           ranges=ranges, expect=expect, anns_motion=job["anns_global"], points_fn=points_fn)
    sugg = fixes.build_suggestions(ctx, medians=medians)
    by_tok = {a["token"]: a for a in job["anns"]}
    # HEADING: ctx['headings'] tinh tren he global -> sinh lai goi y tren he ego (CVAT dung he ego)
    ego_yaw = {i: qc.yaw_of(f["ego_rotation"]) for i, f in enumerate(frames) if "ego_rotation" in f}
    for a_g, _cat, _sev, diff, _speed, vel_yaw in ctx["headings"]:
        a = by_tok[a_g["token"]]
        fr = job["refs"][a["token"]]["frame"]
        sugg[(a["token"], "HEADING_REVERSED")] = fixes.fix_heading(a, diff, vel_yaw - ego_yaw.get(fr, 0.0))
    # BAD_SIZE: neu track du frame nhat quan thi dung kich thuoc cua CHINH track (chinh xac hon trung vi class)
    by_inst = {}
    for a in job["anns"]:
        by_inst.setdefault(a["instance_token"], []).append(a)
    for (tok, issue), _fx in list(sugg.items()):
        if issue != "BAD_SIZE":
            continue
        a = by_tok[tok]
        better = fixes.fix_size_by_track(a, [x for x in by_inst[a["instance_token"]] if x is not a])
        if better:
            sugg[(tok, issue)] = better
    for r in rows:                              # LOW_LIDAR_PTS: chi goi y kiem tra thu cong (BOX_OFFSET lo phan dich box)
        if r[3] == "LOW_LIDAR_PTS" and r[4] != "INFO":
            sugg[(r[1], "LOW_LIDAR_PTS")] = fixes.fix_lidar(by_tok[r[1]], None)
    rows = [r for r in rows if r[1] in job["refs"]]
    rows.sort(key=lambda r: (SEV_ORDER[r[4]], r[3], r[1]))
    return {"rows": rows, "sugg": sugg, "job": job}


def summarize(result):
    """{token: {"issues": [...], "severity": ERROR|WARNING, "notes": [...]}} cho cac cuboid bi co (bo INFO)."""
    out = {}
    for _s, tok, cat, issue, sev, detail in result["rows"]:
        if sev == "INFO":
            continue
        d = out.setdefault(tok, {"issues": [], "severity": sev, "notes": []})
        if issue not in d["issues"]:
            d["issues"].append(issue)
        d["notes"].append("%s: %s" % (issue, detail))
        if SEV_ORDER[sev] < SEV_ORDER[d["severity"]]:
            d["severity"] = sev
    return out


# ------------------------------------------------------------------ ke hoach ghi nguoc (thuan)
def _set_attrs(shape, label_name, attr_ids, values):
    """Dat gia tri attribute (ten -> gia tri) tren mot shape; giu nguyen attribute khac."""
    keep = [a for a in shape.get("attributes", []) if a.get("spec_id") not in
            {attr_ids.get((label_name, n)) for n in values}]
    shape["attributes"] = keep + [{"spec_id": attr_ids[(label_name, n)], "value": v}
                                  for n, v in values.items() if (label_name, n) in attr_ids]


def _fix_allowed(policy, fx, info):
    """Co duoc TU DONG ap dung goi y nay khong (khi --apply)?

    all          : moi goi y co box.
    conservative : chi loai co bang chung tot tren 4 scene nuScenes (evaluate_cvat.py):
                     - lat / can huong: chi khi co ERROR (xe chay nhanh); WARNING (xe cham, co the dang lui) de nguoi quyet
                     - resize THEO TRACK (kich thuoc nhat quan qua cac frame)
                   KHONG tu ap dung: refit (dich box; 118 co nham chi 5% con gan nhan goc) va resize theo class.
    Cac goi y bi chan van duoc tao thanh cuboid QC_SUGGESTION de nguoi duyet."""
    if policy == "all":
        return True
    if fx["kind"] in ("flip_yaw", "align_yaw"):
        return info["severity"] == "ERROR"
    if fx["kind"] == "resize":
        return fx.get("basis") == "track"
    return False


def plan_writeback(annotations, result, label_ids, attr_ids, apply=False, apply_policy="conservative"):
    """Tinh cac thao tac PATCH can thuc hien.

    Tra {"delete": body, "update": body, "create": body, "stats": {...}} (body = {shapes, tracks, tags}).
    Khong goi mang. Khong sua `annotations` (lam viec tren ban sao).
    apply_policy: khi apply=True, loai goi y duoc tu ap dung (conservative | all), xem _fix_allowed.
    """
    skipped = 0
    ann = copy.deepcopy(annotations)
    id2label = {v: k for k, v in label_ids.items()}
    flagged = summarize(result)
    sugg, refs = result["sugg"], result["job"]["refs"]
    sug_label = label_ids.get(SUGGEST_LABEL)

    # 1) xoa cac QC_SUGGESTION cu
    delete = {"shapes": [s for s in ann.get("shapes", []) if s["label_id"] == sug_label], "tracks": [], "tags": []}
    ann["shapes"] = [s for s in ann.get("shapes", []) if s["label_id"] != sug_label]

    # 2) cap nhat attribute (hoac ap dung goi y) tren cac cuboid
    upd_shapes, upd_tracks, touched = {}, {}, set()
    removed_tracks = []

    def shape_iter():
        for s in ann.get("shapes", []):
            if s.get("type") == "cuboid":
                yield "shape", None, s, s["label_id"], "s%s" % s.get("id")
        for t in ann.get("tracks", []):
            for s in t["shapes"]:
                if s.get("type") == "cuboid":
                    yield "track", t, s, t["label_id"], "t%s:%d" % (t.get("id"), s["frame"])

    n_flag = n_applied = 0
    deleted_tokens = set()
    for kind, t, s, label_id, token in shape_iter():
        label_name = id2label.get(label_id)
        if label_name is None or label_name == SUGGEST_LABEL:
            continue
        info = flagged.get(token)
        vals = {"qc_issue": "", "qc_note": ""}
        if info:
            n_flag += 1
            fixes_for = [sugg[(token, i)] for i in info["issues"] if (token, i) in sugg]
            vals = {"qc_issue": "%s %s" % (info["severity"], ", ".join(info["issues"])),
                    "qc_note": " | ".join(info["notes"] + [f["text"] for f in fixes_for])[:1000]}
            if apply:
                auto = None
                for f in fixes_for:
                    if f["kind"] not in AUTO_KINDS or not f.get("box"):
                        continue
                    if not _fix_allowed(apply_policy, f, info):
                        skipped += 1
                        continue
                    auto = f
                    break
                dele = next((f for f in fixes_for if f["kind"] == "delete"), None)
                if auto:
                    s["points"] = ca.box_to_points(auto["box"]["translation"], auto["box"]["size"], auto["box"]["yaw"])
                    vals = {"qc_issue": "", "qc_note": ""}
                    n_applied += 1
                elif dele:
                    deleted_tokens.add(token)
        qc_specs = {attr_ids.get((label_name, n)) for n in ("qc_issue", "qc_note")}
        had_qc = any(a.get("spec_id") in qc_specs and a.get("value") for a in s.get("attributes", []))
        if not info and not had_qc:
            continue                                  # khong co co va chua tung bi danh dau -> khong dong vao
        _set_attrs(s, label_name, attr_ids, vals)
        if True:
            touched.add(token)
            if kind == "track":
                upd_tracks[t["id"]] = t
            else:
                upd_shapes[s["id"]] = s

    # --apply: xoa cuboid trung (ca track neu chi con 1 cuboid that)
    for tid, t in list(upd_tracks.items()):
        real = [s for s in t["shapes"] if not s.get("outside")]
        dead = [s for s in real if "t%s:%d" % (t.get("id"), s["frame"]) in deleted_tokens]
        if dead and len(dead) == len(real):
            removed_tracks.append(t)
            del upd_tracks[tid]
        elif dead:
            for s in dead:
                s["outside"] = True
    for sid, s in list(upd_shapes.items()):
        if "s%s" % sid in deleted_tokens:
            delete["shapes"].append(s)
            del upd_shapes[sid]
    delete["tracks"] += removed_tracks

    # 3) tao QC_SUGGESTION moi (khong tao khi dang --apply)
    create = {"shapes": [], "tracks": [], "tags": []}
    if sug_label is not None and not apply:
        for token, info in flagged.items():
            fx = next((sugg[(token, i)] for i in info["issues"] if (token, i) in sugg
                       and sugg[(token, i)].get("box") and sugg[(token, i)]["kind"] in AUTO_KINDS), None)
            if not fx:
                continue
            b, ref = fx["box"], refs[token]
            shape = {"type": "cuboid", "frame": ref["frame"], "label_id": sug_label, "occluded": False,
                     "outside": False, "z_order": 0, "rotation": 0.0, "group": 0, "source": "auto", "attributes": [],
                     "points": ca.box_to_points(b["translation"], b["size"], b["yaw"])}
            _set_attrs(shape, SUGGEST_LABEL, attr_ids,
                       {"issue": ", ".join(info["issues"]), "target": token, "note": fx["text"][:300]})
            create["shapes"].append(shape)

    return {"delete": delete, "update": {"shapes": list(upd_shapes.values()), "tracks": list(upd_tracks.values()), "tags": []},
            "create": create,
            "stats": {"flagged": n_flag, "suggestions": len(create["shapes"]), "applied": n_applied,
                      "skipped": skipped,
                      "deleted": len(delete["shapes"]) - len([s for s in annotations.get("shapes", [])
                                                              if s["label_id"] == sug_label]) + len(delete["tracks"])}}


def _empty(body):
    return not (body["shapes"] or body["tracks"] or body["tags"])


# ------------------------------------------------------------------ doi chieu voi loi da chen (demo)
def verify_injected(demo_dir, result, annotations_cvat):
    """So khop loi chen (injected.json) voi co cua QC. Tra list dict va in bang."""
    path = os.path.join(demo_dir, "injected.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        injected = json.load(f)
    with open(os.path.join(demo_dir, "annotations.json"), encoding="utf-8") as f:
        neutral = json.load(f)
    # (track_key, frame) -> points da ghi vao CVAT (co the da bi chen loi)
    key_pts = {(t["key"], s["frame"]): s["points"] for t in neutral["tracks"] for s in t["shapes"] if not s["outside"]}
    # khop shape CVAT <-> khoa chen loi theo (frame, points)
    by_geo = {}
    for tok, ref in result["job"]["refs"].items():
        a = next(x for x in result["job"]["anns"] if x["token"] == tok)
        by_geo[(ref["frame"], tuple(round(v, 4) for v in ca.box_to_points(a["translation"], a["size"],
                qc.yaw_of(a["rotation"]))[:9]))] = tok
    flagged = summarize(result)
    anns = result["job"]["anns"]
    out = []
    for inj in injected:
        pts = key_pts.get((inj["track"], inj["frame"]))
        tok = by_geo.get((inj["frame"], tuple(round(v, 4) for v in pts[:9]))) if pts else None
        issues = flagged.get(tok, {}).get("issues", []) if tok else []
        caught = inj["expect_issue"] in issues
        status, iou_now = ("caught" if caught else "missed"), None
        if tok is None and inj.get("original_points"):
            # box loi khong con (da bi sua) -> co box nao o frame do da tro ve box goc khong?
            t, size, yaw = ca.points_to_box(inj["original_points"])
            orig = {"translation": t, "size": list(size), "rotation": ca.quat_from_yaw(yaw)}
            best = 0.0
            for a in anns:
                if result["job"]["refs"][a["token"]]["frame"] != inj["frame"]:
                    continue
                if qc.angle_diff(qc.yaw_of(orig["rotation"]), qc.yaw_of(a["rotation"])) > math.pi / 2:
                    continue                       # IoU hinh hoc khong thay loi lat 180 do
                best = max(best, qc.overlap_3d(orig, a)[0])
            if best >= FIXED_IOU:
                status, iou_now = "fixed", best
        out.append({**inj, "token": tok, "caught": caught, "status": status, "iou_now": iou_now, "issues": issues})
    return out


def collateral_changes(demo_dir, result, radius=3.0):
    """Box GOC DUNG (khong phai loi chen) so voi nhan ban dau trong annotations.json.
    Dung de do 'thiet hai phu' cua --apply khi co nham: box tot bi di chuyen.
    Tra {"n": so box doi chieu, "changed": [{key, frame, iou}], "missing": so box khong con}."""
    with open(os.path.join(demo_dir, "annotations.json"), encoding="utf-8") as f:
        neutral = json.load(f)
    inj_path = os.path.join(demo_dir, "injected.json")
    injected = set()
    if os.path.exists(inj_path):
        with open(inj_path, encoding="utf-8") as f:
            injected = {(i["track"], i["frame"]) for i in json.load(f)}
    anns, refs = result["job"]["anns"], result["job"]["refs"]
    by_frame = {}
    for a in anns:
        by_frame.setdefault(refs[a["token"]]["frame"], []).append(a)
    n, changed, missing = 0, [], 0
    for t in neutral["tracks"]:
        if t["key"].startswith(("dup", "ghost")):
            continue
        for s in t["shapes"]:
            if s["outside"] or (t["key"], s["frame"]) in injected:
                continue
            tr, size, yaw = ca.points_to_box(s["points"])
            gt = {"translation": tr, "size": list(size), "rotation": ca.quat_from_yaw(yaw)}
            cands = [a for a in by_frame.get(s["frame"], []) if refs[a["token"]]["label"] == t["label"]]
            near = min(cands, key=lambda a: math.dist(a["translation"][:2], tr[:2]), default=None)
            n += 1
            if near is None or math.dist(near["translation"][:2], tr[:2]) > radius:
                missing += 1
                continue
            iou = 0.0 if qc.angle_diff(yaw, qc.yaw_of(near["rotation"])) > math.pi / 2 else qc.overlap_3d(gt, near)[0]
            if iou < 0.98:
                changed.append({"key": t["key"], "frame": s["frame"], "iou": iou})
    return {"n": n, "changed": changed, "missing": missing}


def iou_before_after(demo_dir, result, verified):
    """IoU 3D (co huong) so voi box goc truoc loi: truoc = box dang co, sau = box goi y. Chi cho loi co box goc."""
    sugg, anns = result["sugg"], {a["token"]: a for a in result["job"]["anns"]}
    rows = []
    for v in verified:
        if not v["original_points"] or not v["token"]:
            continue
        t, size, yaw = ca.points_to_box(v["original_points"])
        orig = {"translation": t, "size": list(size), "rotation": ca.quat_from_yaw(yaw)}
        cur = anns[v["token"]]
        fx = next((sugg[(v["token"], i)] for i in v["issues"] if (v["token"], i) in sugg and sugg[(v["token"], i)].get("box")), None)
        after = None
        if fx:
            b = fx["box"]
            after = {"translation": b["translation"], "size": list(b["size"]), "rotation": ca.quat_from_yaw(b["yaw"])}

        def oiou(x):
            if x is None:
                return None
            if qc.angle_diff(qc.yaw_of(orig["rotation"]), qc.yaw_of(x["rotation"])) > math.pi / 2:
                return 0.0
            return qc.overlap_3d(orig, x)[0]
        rows.append({"kind": v["kind"], "frame": v["frame"], "before": oiou(cur), "after": oiou(after)})
    return rows


# ------------------------------------------------------------------ chay that
def load_frames_points(demo_dir, meta):
    frames_dir = os.path.join(demo_dir, "frames")

    def get(i):
        return cvat_demo.read_pcd(os.path.join(frames_dir, meta[i]["name"]))
    return get


def run(demo_dir, profile_path, apply=False, dry_run=False, report=str(paths.DATA / "qc_report.csv"), client=None,
        apply_policy="conservative"):
    with open(os.path.join(demo_dir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)["frames"]
    c = client or Client.from_env()
    with open(os.path.join(demo_dir, "cvat_ids.json"), encoding="utf-8") as f:
        ids = json.load(f)
    jid, tid, pid = ids["job_id"], ids["task_id"], ids["project_id"]
    labels = c.labels(project_id=pid)
    label_ids = {l["name"]: l["id"] for l in labels}
    attr_ids = {(l["name"], a["name"]): a["id"] for l in labels for a in l.get("attributes", [])}
    id2label = {v: k for k, v in label_ids.items()}

    annotations = c.get_annotations(jid)
    result = analyze_job(annotations, id2label, meta, load_frames_points(demo_dir, meta), profile_path)
    flagged = summarize(result)
    from collections import Counter
    cnt = Counter(i for d in flagged.values() for i in d["issues"])
    n_shapes = len(result["job"]["anns"])
    print("Cuboid trong job: %d, bi co: %d (%.1f%%)" % (n_shapes, len(flagged), 100.0 * len(flagged) / max(n_shapes, 1)))
    for issue, n in sorted(cnt.items()):
        print("  %-18s %d" % (issue, n))

    with open(paths.ensure_parent(report), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["token", "track_id", "frame", "label", "issue", "severity", "detail"])
        for _s, tok, _c, issue, sev, detail in result["rows"]:
            ref = result["job"]["refs"][tok]
            w.writerow([tok, ref["track_id"], ref["frame"], ref["label"], issue, sev, detail])

    verified = verify_injected(demo_dir, result, annotations)
    if verified:
        print("\nLoi da chen (kiem chung):")
        for v in verified:
            label = {"caught": "BAT (dang bi co)",
                     "fixed": "DA SUA (IoU voi box goc %.2f)" % (v["iou_now"] or 0),
                     "missed": "BO SOT (%s)" % (", ".join(v["issues"]) or "khong co")}[v["status"]]
            print("  %-18s frame %-2d %-18s -> %s" % (v["kind"], v["frame"], v["expect_issue"], label))
        n_caught = sum(v["status"] == "caught" for v in verified)
        n_fixed = sum(v["status"] == "fixed" for v in verified)
        print("  Dang bi co: %d, da sua: %d, bo sot: %d (tong %d loi chen)" %
              (n_caught, n_fixed, len(verified) - n_caught - n_fixed, len(verified)))
        col = collateral_changes(demo_dir, result)
        if col["n"]:
            mean_iou = sum(c["iou"] for c in col["changed"]) / len(col["changed"]) if col["changed"] else 1.0
            print("  Box nhan goc KHONG phai loi chen: %d; bi doi vi tri/kich thuoc: %d (IoU TB voi nhan goc %.2f); bi mat: %d" %
                  (col["n"], len(col["changed"]), mean_iou, col["missing"]))
        gains = [r for r in iou_before_after(demo_dir, result, verified) if r["after"] is not None]
        if gains:
            print("  IoU 3D voi box goc: %.2f (truoc) -> %.2f (sau khi ap dung goi y), %d loi co goi y box" %
                  (sum(r["before"] for r in gains) / len(gains), sum(r["after"] for r in gains) / len(gains), len(gains)))

    plan = plan_writeback(annotations, result, label_ids, attr_ids, apply=apply, apply_policy=apply_policy)
    print("\nKe hoach ghi vao CVAT: %s" % plan["stats"])
    if apply and plan["stats"]["skipped"]:
        print("(--apply-policy %s: giu lai %d goi y cho nguoi quyet dinh, khong tu ap dung)" %
              (apply_policy, plan["stats"]["skipped"]))
    if dry_run:
        print("(--dry-run: khong ghi gi vao CVAT)")
        return result, plan
    for action in ("delete", "update", "create"):
        if not _empty(plan[action]):
            c.patch_annotations(jid, action, plan[action])
    print("Da ghi vao CVAT. Mo job: %s" % c.job_url(tid, jid))
    return result, plan


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--demo", default=str(paths.DEMO))
    ap.add_argument("--profile", default=str(paths.PROFILE))
    ap.add_argument("--apply", action="store_true", help="ap dung cac goi y tu dong sua vao cuboid goc")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=str(paths.DATA / "qc_report.csv"))
    ap.add_argument("--apply-policy", choices=["conservative", "all"], default="conservative",
                    help="khi --apply: conservative (mac dinh) chi tu ap dung loai goi y co bang chung tot; "
                         "all ap dung moi goi y co box (co the lam hong nhan dung)")
    args = ap.parse_args()
    run(args.demo, args.profile, args.apply, args.dry_run, args.report, apply_policy=args.apply_policy)


if __name__ == "__main__":
    main()

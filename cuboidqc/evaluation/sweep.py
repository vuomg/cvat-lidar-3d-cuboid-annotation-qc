#!/usr/bin/env python3
"""Quet 1 tham so qua nhieu gia tri, in recall (>=WARNING) tung muc + so co tren GT goc.

  python -m cuboidqc.evaluation.sweep --dataroot V:\\data\\nuscenes --issue BAD_SIZE --param HARD_FACTOR 1.5 1.25 1.1
"""
import argparse

from cuboidqc.evaluation import nuscenes as ev
from cuboidqc.core import qc as qc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataroot", required=True)
    ap.add_argument("--version", default="v1.0-mini")
    ap.add_argument("--issue", required=True)
    ap.add_argument("--param", nargs="+", required=True, help="TEN gia_tri1 gia_tri2 ...")
    ap.add_argument("--seeds", type=int, default=2)
    args = ap.parse_args()
    name, values = args.param[0], [float(v) for v in args.param[1:]]
    ctx = ev.Ctx(args.dataroot, args.version)
    default = getattr(qc, name)
    try:
        for v in values:
            setattr(qc, name, int(v) if isinstance(default, int) else v)
            r = ev.evaluate(ctx, args.seeds, (args.issue,))[args.issue]
            prec = 100.0 * r["tp"] / max(r["tp"] + r["fp"], 1)
            rec = "  ".join("%s=%.0f%%" % (k, 100.0 * a / t) for k, (t, a, e, u) in r["levels"].items())
            print("%s=%g | co tren GT: %d | precision>= %.0f%% | recall: %s" %
                  (name, v, r["clean_flags"], prec, rec))
    finally:
        setattr(qc, name, default)
        ctx.close()


if __name__ == "__main__":
    main()

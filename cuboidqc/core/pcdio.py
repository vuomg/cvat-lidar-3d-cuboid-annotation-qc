"""Doc / ghi file PCD (ASCII hoac nhi phan) tu / ra bytes. Chi can truong x y z."""
import io

import numpy as np

_CODES = {("F", 4): "<f4", ("F", 8): "<f8", ("U", 1): "u1", ("U", 2): "<u2", ("U", 4): "<u4",
          ("I", 1): "i1", ("I", 2): "<i2", ("I", 4): "<i4"}


def parse_pcd(data):
    """bytes cua file .pcd -> mang Nx3 float64 (x, y, z), da bo diem NaN/inf."""
    f = io.BytesIO(data)
    header = {}
    while True:
        line = f.readline()
        if not line:
            raise ValueError("PCD thieu dong DATA")
        s = line.decode("ascii", "ignore").strip()
        if not s or s.startswith("#"):
            continue
        key, *val = s.split()
        header[key.upper()] = val
        if key.upper() == "DATA":
            break
    fields, sizes, types = header["FIELDS"], [int(x) for x in header["SIZE"]], header["TYPE"]
    counts = [int(x) for x in header.get("COUNT", ["1"] * len(fields))]
    n = int(header["POINTS"][0])
    mode = header["DATA"][0].lower()
    if mode == "ascii":
        raw = np.loadtxt(f, dtype=np.float64, ndmin=2)
        cols, i = {}, 0
        for name, c in zip(fields, counts):
            cols.setdefault(name, raw[:, i])
            i += c
    elif mode == "binary":
        dt = []
        for i, (name, size, typ, c) in enumerate(zip(fields, sizes, types, counts)):
            code = _CODES[(typ, size)]
            dt.append(("%s_%d" % (name, i), code, (c,)) if c > 1 else ("%s_%d" % (name, i), code))
        arr = np.frombuffer(f.read(), dtype=np.dtype(dt), count=n)
        cols = {}
        for i, name in reversed(list(enumerate(fields))):          # truong dau tien trung ten thang
            cols[name] = arr["%s_%d" % (name, i)].astype(np.float64).reshape(n, -1)[:, 0]
    else:
        raise NotImplementedError("DATA %s" % mode)
    for need in ("x", "y", "z"):
        if need not in cols:
            raise ValueError("PCD thieu truong %s" % need)
    P = np.stack([cols["x"], cols["y"], cols["z"]], axis=1)
    return P[np.isfinite(P).all(axis=1)]


def pcd_bytes(pts):
    """Nx4 (x, y, z, intensity) float32 -> bytes PCD nhi phan."""
    n = len(pts)
    header = ("# .PCD v0.7\nVERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\nTYPE F F F F\nCOUNT 1 1 1 1\n"
              "WIDTH %d\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS %d\nDATA binary\n" % (n, n))
    return header.encode("ascii") + np.ascontiguousarray(pts, dtype="<f4").tobytes()

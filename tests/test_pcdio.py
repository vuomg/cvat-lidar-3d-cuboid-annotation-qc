"""Test pcdio: doc / ghi PCD tu bytes (nhi phan, ascii, nhieu truong, NaN)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cuboidqc.core import pcdio as pcdio  # noqa: E402


class TestPcd(unittest.TestCase):
    def test_binary_roundtrip(self):
        pts = np.array([[1.5, -2.0, 0.25, 7.0], [10.0, 20.0, 30.0, 1.0]], dtype=np.float32)
        out = pcdio.parse_pcd(pcdio.pcd_bytes(pts))
        np.testing.assert_allclose(out, pts[:, :3], atol=1e-6)

    def test_ascii(self):
        data = b"# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH 2\nHEIGHT 1\nPOINTS 2\nDATA ascii\n1 2 3\n4 5 6\n"
        out = pcdio.parse_pcd(data)
        np.testing.assert_allclose(out, [[1, 2, 3], [4, 5, 6]])

    def test_extra_fields_in_different_order(self):
        """intensity truoc xyz va them truong rgb: van lay dung x y z."""
        header = (b"VERSION 0.7\nFIELDS intensity x y z rgb\nSIZE 4 4 4 4 4\nTYPE F F F F U\nCOUNT 1 1 1 1 1\n"
                  b"WIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA binary\n")
        body = np.array([(9.0, 1.0, 2.0, 3.0, 255)], dtype=[("i", "<f4"), ("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("c", "<u4")]).tobytes()
        np.testing.assert_allclose(pcdio.parse_pcd(header + body), [[1, 2, 3]])

    def test_nan_points_dropped(self):
        pts = np.array([[1, 2, 3, 0], [np.nan, 2, 3, 0], [4, 5, 6, 0]], dtype=np.float32)
        self.assertEqual(len(pcdio.parse_pcd(pcdio.pcd_bytes(pts))), 2)

    def test_missing_data_line_raises(self):
        with self.assertRaises(ValueError):
            pcdio.parse_pcd(b"VERSION 0.7\nFIELDS x y z\n")

    def test_missing_xyz_field_raises(self):
        data = b"VERSION 0.7\nFIELDS x y\nSIZE 4 4\nTYPE F F\nCOUNT 1 1\nWIDTH 1\nHEIGHT 1\nPOINTS 1\nDATA ascii\n1 2\n"
        with self.assertRaises(ValueError):
            pcdio.parse_pcd(data)


if __name__ == "__main__":
    unittest.main()

"""Moi duong dan mac dinh cua du an o mot cho (tinh theo vi tri thu muc goc, khong theo thu muc dang dung)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"
DATA = ROOT / "data"                       # du lieu SINH RA khi chay (khong dua vao git)
DOCS = ROOT / "docs"
REPORTS = DOCS / "reports"

PROFILE = CONFIGS / "profile.json"
CONFIG = CONFIGS / "config.json"
DEMO = DATA / "demo_data"
CALIB = DATA / "calib_data"
LOGS = DATA / "logs"
TOKEN_FILE = ROOT / ".qc_token"
LOGIN_FILE = ROOT / ".cvat_login.xml"


def ensure_parent(path):
    """Tao thu muc cha cua mot duong dan file (neu chua co); tra ve chinh duong dan."""
    d = os.path.dirname(str(path))
    if d:
        os.makedirs(d, exist_ok=True)
    return path

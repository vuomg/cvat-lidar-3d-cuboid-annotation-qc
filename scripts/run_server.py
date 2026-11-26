#!/usr/bin/env python3
"""Chay server QC tu bat ky thu muc nao (tu them thu muc goc vao sys.path).

  python scripts/run_server.py [--meta data/demo_data/meta.json] [--port 8766] ...
Moi tham so duoc chuyen cho cuboidqc.server.app (xem: python scripts/run_server.py --help).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cuboidqc.server.app import main  # noqa: E402

if __name__ == "__main__":
    main()

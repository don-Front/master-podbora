# -*- coding: utf-8 -*-
"""Install nginx on master-turbo-podbor.ru VPS (wrapper for setup_master_vps_nginx.py)."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "setup_master_vps_nginx.py"
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")

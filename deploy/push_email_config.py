# -*- coding: utf-8 -*-
"""Upload email_config.py to master-turbo-podbor.ru VPS (FastAPI)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "email_config.py"
REMOTE = "/opt/turbo-podbor/email_config.py"
HOST = os.environ.get("MASTER_VPS_HOST", "31.128.47.176")
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")


def main() -> int:
    if not PASSWORD:
        print("Set MASTER_VPS_PASSWORD")
        return 1
    if not LOCAL.is_file():
        print(f"Missing {LOCAL}")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username="root", password=PASSWORD, timeout=25, allow_agent=False, look_for_keys=False
    )
    sftp = client.open_sftp()
    sftp.put(str(LOCAL), REMOTE)
    sftp.close()

    _, stdout, _ = client.exec_command(
        f"grep -E 'MANAGER_EMAIL|RECEIVER_EMAIL' {REMOTE} | head -5", timeout=20
    )
    print(stdout.read().decode(errors="replace").strip())
    client.close()
    print(f"OK: {REMOTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

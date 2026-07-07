# -*- coding: utf-8 -*-
"""Заливка tkp_accessories.py на master VPS и перезапуск turbo-podbor."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "tkp_accessories.py"
REMOTE = "/opt/turbo-podbor/tkp_accessories.py"
HOST = os.environ.get("MASTER_VPS_HOST", "31.128.47.176")
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")


def main() -> int:
    if not PASSWORD:
        print("Set MASTER_VPS_PASSWORD", file=sys.stderr)
        return 1
    if not LOCAL.is_file():
        print(f"Missing {LOCAL}", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username="root",
        password=PASSWORD,
        timeout=25,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = client.open_sftp()
    sftp.put(str(LOCAL), REMOTE)
    sftp.close()

    for cmd in [
        f"grep -n def\\ tkp_accessories_from_request {REMOTE} | head -1",
        "systemctl restart turbo-podbor 2>/dev/null || systemctl restart turbo-podbor.service",
        "sleep 3",
        "curl -sS -m 10 -o /dev/null -w 'health:%{http_code}\\n' http://127.0.0.1:8080/health || true",
        (
            "curl -sS -m 15 -X POST http://127.0.0.1:8080/api/tkp-accessories "
            "-H 'Content-Type: application/json' "
            "-d '{\"equipment\":{\"id\":\"ufg2\"},\"dn\":100,\"pressure_max_mpa\":2.5,\"accuracy_percent\":1}' "
            "| head -c 200"
        ),
    ]:
        _, stdout, stderr = client.exec_command(cmd, timeout=60)
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        if out:
            print(out)
        if err:
            print("ERR:", err[:300], file=sys.stderr)

    client.close()
    print(f"OK: {REMOTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

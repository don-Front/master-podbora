# -*- coding: utf-8 -*-
import os
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PWD = os.environ.get("MASTER_VPS_PASSWORD", "DVPozOfj0DwPmoxT")
HOST = os.environ.get("DEPLOY_HOST", "193.105.37.142")

CMDS = [
    "hostname",
    "ss -lntp 2>/dev/null | grep 10112 || true",
    "ps aux | grep daphne | grep -v grep | head -10",
    "find /opt /root /home /var -maxdepth 8 -path '*/chatbot/manage.py' 2>/dev/null | head -10",
    "find /opt /root /home /var -maxdepth 8 -name run_daphne.ps1 2>/dev/null | head -5",
]


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username="root", password=PWD, timeout=25, allow_agent=False, look_for_keys=False
    )
    for cmd in CMDS:
        print(f"=== {cmd} ===")
        _, stdout, stderr = client.exec_command(cmd, timeout=60)
        print(stdout.read().decode("utf-8", errors="replace"))
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if err:
            print("stderr:", err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

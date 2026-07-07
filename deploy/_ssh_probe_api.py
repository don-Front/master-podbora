# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PWD = os.environ.get("TKP_VPS_PASSWORD", "DVPozOfj0DwPmoxT")
HOSTS = ["193.105.37.142", "31.128.47.176"]


def run(client: paramiko.SSHClient, cmd: str) -> None:
    _, stdout, stderr = client.exec_command(cmd, timeout=30)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    print(f"$ {cmd}")
    if out:
        print(out)
    if err:
        print("stderr:", err)


def main() -> int:
    for host in HOSTS:
        print(f"\n=== {host} ===")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                host,
                username="root",
                password=PWD,
                timeout=20,
                allow_agent=False,
                look_for_keys=False,
            )
        except Exception as exc:
            print("connect FAIL:", exc)
            continue
        run(client, "hostname")
        run(
            client,
            "curl -s -o /dev/null -w 'hints:%{http_code}\\n' "
            "'http://127.0.0.1:10112/api/hints/?state=start'",
        )
        run(
            client,
            "curl -s -o /tmp/create.html -w 'create:%{http_code}\\n' "
            "-X POST 'http://127.0.0.1:10112/api/chats/' "
            "-H 'Content-Type: application/json' -d '{\"title\":\"diag\"}'",
        )
        run(
            client,
            "grep -o 'no such table: [^<]*' /tmp/create.html | head -1 || true",
        )
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

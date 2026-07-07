# -*- coding: utf-8 -*-
"""Diagnose and fix missing api_chat table on production Django."""
from __future__ import annotations

import json
import os
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "DVPozOfj0DwPmoxT")
HOSTS = ["31.128.47.176", "193.105.37.142"]


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 60) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out)
    if err:
        print("stderr:", err)
    return out


def main() -> int:
    print("=== production probe ===")
    run_remote = paramiko.SSHClient()
    run_remote.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    run_remote.connect(
        "31.128.47.176",
        username="root",
        password=PASSWORD,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    run(
        run_remote,
        "curl -s -o /tmp/chat_create.html -w 'prod_create:%{http_code}\\n' "
        "-X POST 'https://master-turbo-podbor.ru/podbor-api/api/chats/' "
        "-H 'Content-Type: application/json' -d '{\"title\":\"diag\"}'",
    )
    run(run_remote, "grep -o 'no such table: [^<]*' /tmp/chat_create.html | head -1 || true")
    run_remote.close()

    for host in HOSTS:
        print(f"\n=== {host} ===")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                host,
                username="root",
                password=PASSWORD,
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
            "ss -lntp 2>/dev/null | grep 10112 || netstat -lntp 2>/dev/null | grep 10112 || true",
        )
        run(
            client,
            "ps aux | grep -E 'daphne|manage.py|gunicorn|uvicorn' | grep -v grep | head -10",
        )
        run(
            client,
            "find /opt /root /home -maxdepth 5 -name 'manage.py' 2>/dev/null | head -10",
        )
        run(
            client,
            "find /opt /root /home -maxdepth 6 -path '*/chatbot/manage.py' 2>/dev/null | head -5",
        )
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

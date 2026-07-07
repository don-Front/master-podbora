# -*- coding: utf-8 -*-
"""Enable HTTPS (Let's Encrypt) on master-turbo-podbor.ru via certbot."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("MASTER_VPS_HOST", "31.128.47.176")
USER = os.environ.get("MASTER_VPS_USER", "root")
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")
DOMAIN = "master-turbo-podbor.ru"
EMAIL = os.environ.get("MASTER_VPS_LE_EMAIL", "info@turbo-don.ru")

VERIFY_CMDS = (
    f"curl -sk -o /dev/null -w 'https_chat:%{{http_code}}\\n' https://127.0.0.1/podbor-chat/ -H 'Host: {DOMAIN}'",
    f"curl -sk -o /dev/null -w 'https_widget:%{{http_code}}\\n' https://127.0.0.1/podbor-chat/widget.js -H 'Host: {DOMAIN}'",
    f"curl -sk -o /dev/null -w 'https_api:%{{http_code}}\\n' 'https://127.0.0.1/podbor-api/api/hints/?state=start' -H 'Host: {DOMAIN}'",
    f"curl -sk -o /dev/null -w 'https_fastapi:%{{http_code}}\\n' https://127.0.0.1/api/search-equipment -H 'Host: {DOMAIN}'",
    "ss -lntp | grep -E ':443|:80' || true",
)


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 300) -> tuple[str, str, int]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return out, err, code


def main() -> int:
    if not PASSWORD:
        print("Set MASTER_VPS_PASSWORD")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username=USER, password=PASSWORD, timeout=25, allow_agent=False, look_for_keys=False
    )
    print(f"SSH ok: {USER}@{HOST}")

    steps = [
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get update -qq",
        "apt-get install -y -qq certbot python3-certbot-nginx",
        f"dig +short {DOMAIN}; dig +short www.{DOMAIN}",
        (
            f"certbot --nginx --non-interactive --agree-tos "
            f"--email {EMAIL} -d {DOMAIN} --redirect"
        ),
        "systemctl enable certbot.timer",
        "systemctl start certbot.timer",
        "nginx -t",
        "systemctl reload nginx",
    ]

    for step in steps:
        print(f"\n$ {step}")
        out, err, code = run(client, step, timeout=600)
        combined = "\n".join(x for x in (out, err) if x)
        print(combined[:2000] if combined else "(empty)")
        if code != 0 and "certbot" in step:
            print(f"certbot failed (exit {code})")
            client.close()
            return 1

    print("\nVerification:")
    for cmd in VERIFY_CMDS:
        out, err, _ = run(client, cmd, timeout=30)
        print(f"$ {cmd}")
        print(out or err or "(empty)")

    client.close()
    print("\nHTTPS setup done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Install nginx on master-turbo-podbor.ru VPS and configure podbor-chat/podbor-api proxy."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
NGINX_CONF_LOCAL = ROOT / "deploy" / "nginx-master-turbo-podbor-full.conf"
NGINX_CONF_REMOTE = "/etc/nginx/sites-available/master-turbo-podbor.ru"
SERVICE_FILE = "/etc/systemd/system/turbo-podbor.service"
FASTAPI_PORT = "8080"

HOST = os.environ.get("MASTER_VPS_HOST", "31.128.47.176")
USER = os.environ.get("MASTER_VPS_USER", "root")
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")

VERIFY_CMDS = (
    "curl -s -o /dev/null -w 'fastapi:%{http_code}\\n' http://127.0.0.1/api/search-equipment",
    "curl -s -o /dev/null -w 'chat:%{http_code}\\n' http://127.0.0.1/podbor-chat/",
    "curl -s -o /dev/null -w 'widget:%{http_code}\\n' http://127.0.0.1/podbor-chat/widget.js",
    "curl -s -o /dev/null -w 'api:%{http_code}\\n' 'http://127.0.0.1/podbor-api/api/hints/?state=start'",
)


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[str, str, int]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace").strip()
    err = stderr.read().decode(errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return out, err, code


def main() -> int:
    if not PASSWORD:
        print("Set MASTER_VPS_PASSWORD environment variable")
        return 1
    if not NGINX_CONF_LOCAL.is_file():
        print(f"Missing {NGINX_CONF_LOCAL}")
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
        "apt-get install -y -qq nginx",
        f"sed -i 's/--port 80/--port {FASTAPI_PORT}/' {SERVICE_FILE}",
        "systemctl daemon-reload",
        "systemctl restart turbo-podbor",
        "sleep 2",
    ]
    for step in steps:
        print(f"$ {step}")
        out, err, code = run(client, step)
        if out:
            print(out[:500])
        if err and code != 0:
            print("ERR:", err[:500])
            client.close()
            return 1

    sftp = client.open_sftp()
    sftp.put(str(NGINX_CONF_LOCAL), NGINX_CONF_REMOTE)
    sftp.close()

    post_steps = [
        f"ln -sf {NGINX_CONF_REMOTE} /etc/nginx/sites-enabled/master-turbo-podbor.ru",
        "rm -f /etc/nginx/sites-enabled/default",
        "nginx -t",
        "systemctl enable nginx",
        "systemctl restart nginx",
    ]
    for step in post_steps:
        print(f"$ {step}")
        out, err, code = run(client, step)
        combined = out or err
        print(combined[:500] if combined else "(empty)")
        if code != 0:
            print(f"FAILED (exit {code})")
            client.close()
            return 1

    print("\nVerification:")
    for cmd in VERIFY_CMDS:
        out, err, _ = run(client, cmd, timeout=30)
        print(f"$ {cmd}")
        print(out or err or "(empty)")

    client.close()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

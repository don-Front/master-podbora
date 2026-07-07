# -*- coding: utf-8 -*-
"""Deploy nginx port-forward config on 193.105.37.142 (when SSH is available)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
CONF_LOCAL = ROOT / "deploy" / "nginx-193.105.37.142-ports.conf"
CONF_REMOTE = "/etc/nginx/conf.d/master-podbora-ports.conf"

HOST = os.environ.get("GATEWAY_HOST", "193.105.37.142")
USER = os.environ.get("GATEWAY_USER", "root")
PASSWORD = os.environ.get("GATEWAY_PASSWORD", os.environ.get("TKP_VPS_PASSWORD", "DVPozOfj0DwPmoxT"))
SSH_PORTS = [
    int(p)
    for p in os.environ.get("GATEWAY_SSH_PORTS", "22,2222,22022").split(",")
    if p.strip()
]


def connect() -> paramiko.SSHClient:
    last_error: Exception | None = None
    for port in SSH_PORTS:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                HOST,
                port=port,
                username=USER,
                password=PASSWORD,
                timeout=20,
                allow_agent=False,
                look_for_keys=False,
            )
            print(f"SSH ok: {USER}@{HOST}:{port}")
            return client
        except Exception as exc:
            last_error = exc
            print(f"SSH fail {HOST}:{port} -> {exc}")
    raise RuntimeError(f"Cannot SSH to {HOST}") from last_error


def main() -> int:
    if not CONF_LOCAL.is_file():
        print(f"Missing config: {CONF_LOCAL}")
        return 1

    client = connect()
    sftp = client.open_sftp()
    sftp.put(str(CONF_LOCAL), CONF_REMOTE)
    sftp.close()

    for cmd in ("nginx -t", "systemctl reload nginx || service nginx reload"):
        _, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        print(f"$ {cmd}")
        if out.strip():
            print(out.strip())
        if err.strip():
            print(err.strip())

    for probe in (
        "curl -s -o /dev/null -w 'gw_ui:%{http_code}\\n' http://127.0.0.1:10111/",
        "curl -s -o /dev/null -w 'gw_api:%{http_code}\\n' 'http://127.0.0.1:10112/api/hints/?state=start'",
    ):
        _, stdout, stderr = client.exec_command(probe, timeout=30)
        print(stdout.read().decode(errors="replace").strip() or stderr.read().decode(errors="replace").strip())

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

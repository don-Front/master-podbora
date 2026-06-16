"""Заливка tkp_pdf.py в turbo-podbor-app и перезапуск контейнера."""
import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("TKP_VPS_HOST", "80.78.245.56")
USER = os.environ.get("TKP_VPS_USER", "root")
PASSWORD = os.environ.get("TKP_VPS_PASSWORD", "")
LOCAL = Path(__file__).resolve().parent / "tkp_pdf.py"
REMOTE_TMP = "/root/tkp_pdf_fixed.py"
CONTAINER = "turbo-podbor-app"


def main() -> int:
    if not PASSWORD:
        print("Задайте TKP_VPS_PASSWORD", file=sys.stderr)
        return 1
    if not LOCAL.is_file():
        print(f"Нет файла {LOCAL}", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    sftp.put(str(LOCAL), REMOTE_TMP)
    sftp.close()

    for cmd in [
        f"docker cp {REMOTE_TMP} {CONTAINER}:/app/tkp_pdf.py",
        f"docker exec {CONTAINER} rm -rf /app/__pycache__ 2>/dev/null; true",
        f"docker restart {CONTAINER}",
        "sleep 4",
        f"docker exec {CONTAINER} grep -n draw_dash_separator /app/tkp_pdf.py | head -3",
    ]:
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        if out.strip():
            print(out[:800])
        if err.strip():
            print("ERR:", err[:300], file=sys.stderr)

    client.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

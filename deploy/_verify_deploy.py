# -*- coding: utf-8 -*-
import os
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = os.environ.get("TKP_VPS_HOST", "31.128.47.176")
USER = os.environ.get("TKP_VPS_USER", "root")
PASSWORD = os.environ.get("TKP_VPS_PASSWORD", "DVPozOfj0DwPmoxT")

CMDS = [
    "curl -s -o /dev/null -w 'prod_sc:%{http_code} size:%{size_download}\\n' "
    "https://master-turbo-podbor.ru/podbor-api/api/service-centers/",
    "curl -s -o /dev/null -w 'prod_memo:%{http_code} size:%{size_download}\\n' "
    "https://master-turbo-podbor.ru/podbor-api/api/faq-attachments/repair-memo/",
    "curl -s https://master-turbo-podbor.ru/podbor-chat/index.html | "
    "grep -o 'main\\.[a-f0-9]*\\.js' | head -1",
    "curl -s -o /dev/null -w 'remote_sc:%{http_code}\\n' "
    "http://193.105.37.142:10112/api/service-centers/",
    "curl -s -o /dev/null -w 'remote_ui:%{http_code}\\n' "
    "http://193.105.37.142:10111/index.html",
]


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username=USER, password=PASSWORD, timeout=20, allow_agent=False, look_for_keys=False
    )
    for cmd in CMDS:
        _, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        print(out or err or "(empty)")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

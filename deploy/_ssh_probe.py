# -*- coding: utf-8 -*-
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOSTS = ["193.105.37.142", "80.78.245.56"]
PASSWORD = "DVPozOfj0DwPmoxT"
CMD = "hostname; ss -lntp 2>/dev/null | head -30 || netstat -lntp 2>/dev/null | head -30"

for host in HOSTS:
    print(f"=== {host} ===")
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
        _, stdout, stderr = client.exec_command(CMD, timeout=30)
        print(stdout.read().decode(errors="replace"))
        err = stderr.read().decode(errors="replace")
        if err.strip():
            print("stderr:", err)
        client.close()
    except Exception as exc:
        print("FAIL:", exc)

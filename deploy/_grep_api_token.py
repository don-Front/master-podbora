# -*- coding: utf-8 -*-
import os
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "31.128.47.176",
    username="root",
    password=os.environ["MASTER_VPS_PASSWORD"],
    timeout=25,
)
for cmd in [
    "grep -n support-request /opt/turbo-podbor/main.py | head -10",
    "grep API_TOKEN /opt/turbo-podbor/.env 2>/dev/null || echo no-env",
    "cat /opt/turbo-podbor/.env 2>/dev/null | grep -i token || true",
]:
    _, o, _ = c.exec_command(cmd)
    print(">", cmd)
    print(o.read().decode("utf-8", "replace"))
c.close()

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
_, o, _ = c.exec_command("systemctl cat turbo-podbor 2>/dev/null || ps aux | grep uvicorn | grep -v grep")
print(o.read().decode("utf-8", "replace"))
c.close()

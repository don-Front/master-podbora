# -*- coding: utf-8 -*-
import os
import paramiko
from pathlib import Path

ROOT = Path(__file__).resolve().parent
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "31.128.47.176",
    username="root",
    password=os.environ["MASTER_VPS_PASSWORD"],
    timeout=25,
)
_, o, _ = c.exec_command("sed -n '220,230p;5020,5120p' /opt/turbo-podbor/main.py")
(ROOT / "_vps_analytics_snippet.txt").write_text(
    o.read().decode("utf-8", "replace"), encoding="utf-8"
)
print("written")
c.close()

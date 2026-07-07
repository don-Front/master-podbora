# -*- coding: utf-8 -*-
import os
import paramiko
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "31.128.47.176"
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", password=PASSWORD, timeout=25)
sftp = client.open_sftp()
sftp.get("/opt/turbo-podbor/email_templates.py", str(ROOT / "email_templates_from_vps.py"))
sftp.close()
client.close()
print("done")

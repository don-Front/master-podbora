# -*- coding: utf-8 -*-
import os
import paramiko
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "31.128.47.176"
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")

FILES = [
    "/opt/turbo-podbor/manager_notifications.py",
    "/opt/turbo-podbor/email_config.py",
]

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", password=PASSWORD, timeout=25)
sftp = client.open_sftp()

for remote in FILES:
    name = Path(remote).name
    local = ROOT / name.replace(".py", "_from_vps.py")
    sftp.get(remote, str(local))
    print(f"Downloaded {remote} -> {local}")

sftp.close()
client.close()

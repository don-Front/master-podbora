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

_, stdout, _ = client.exec_command(
    "grep -n 'def notify_manager' /opt/turbo-podbor/main.py /opt/turbo-podbor/*.py 2>/dev/null"
)
print(stdout.read().decode("utf-8", "replace"))

for fname in ["main.py", "notification_emails.py", "email_notifications.py", "manager_notifications.py"]:
    path = f"/opt/turbo-podbor/{fname}"
    _, stdout, _ = client.exec_command(f"test -f {path} && echo EXISTS")
    if b"EXISTS" in stdout.read():
        print(f"Found: {path}")

_, stdout, _ = client.exec_command("ls /opt/turbo-podbor/*.py")
print(stdout.read().decode("utf-8", "replace"))

client.close()

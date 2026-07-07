# -*- coding: utf-8 -*-
import os
import paramiko

HOST = "31.128.47.176"
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")
REMOTE = "/opt/turbo-podbor/main.py"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", password=PASSWORD, timeout=25)

patterns = [
    "send-price-inquiry",
    "send-tkp-request",
    "msg['To']",
    "RECEIVER_EMAIL",
    "build_notification",
    "html_email",
    "send_notification",
    "MANAGER_EMAIL",
]

for pat in patterns:
    _, stdout, _ = client.exec_command(f"grep -n '{pat}' {REMOTE} 2>/dev/null | sed -n '1,25p'")
    out = stdout.read().decode("utf-8", "replace").strip()
    if out:
        print(f"=== {pat} ===")
        print(out)
        print()

_, stdout, _ = client.exec_command(f"grep -n 'def send_' {REMOTE} 2>/dev/null | sed -n '1,40p'")
print("=== def send_ ===")
print(stdout.read().decode("utf-8", "replace").strip())

client.close()

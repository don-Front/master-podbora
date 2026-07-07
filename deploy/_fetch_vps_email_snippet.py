# -*- coding: utf-8 -*-
import os
import paramiko
from pathlib import Path

ROOT = Path(__file__).resolve().parent

HOST = "31.128.47.176"
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")
REMOTE = "/opt/turbo-podbor/main.py"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", password=PASSWORD, timeout=25)

for start, end in [(4780, 4930), (4560, 4680)]:
    _, stdout, _ = client.exec_command(f"sed -n '{start},{end}p' {REMOTE}")
    chunk = stdout.read().decode("utf-8", "replace")
    out_path = ROOT / f"_vps_email_{start}_{end}.txt"
    out_path.write_text(chunk, encoding="utf-8")
    print(f"Wrote {out_path} ({len(chunk)} chars)")

client.close()

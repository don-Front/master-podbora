import os
from pathlib import Path

import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "80.78.245.56",
    username="root",
    password=os.environ["TKP_VPS_PASSWORD"],
    timeout=20,
    allow_agent=False,
    look_for_keys=False,
)
cmds = [
    "docker exec turbo-podbor-app grep -n verification_codes /app/main.py",
]
out_path = __file__.replace("_inspect_verify.py", "_inspect_verify_out.txt")
parts = []
for cmd in cmds:
    _, o, e = c.exec_command(cmd, timeout=60)
    parts.append(f"=== {cmd}\n")
    parts.append(o.read().decode(errors="replace")[:8000])
    err = e.read().decode(errors="replace")
    if err.strip():
        parts.append(f"ERR: {err[:200]}\n")
c.close()
Path(out_path).write_text("".join(parts), encoding="utf-8")
print("written", out_path)

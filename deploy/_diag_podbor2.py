import os
from pathlib import Path
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("80.78.245.56", username="root", password=os.environ["TKP_VPS_PASSWORD"], timeout=20, allow_agent=False, look_for_keys=False)
cmds = [
    "curl -sk -o /dev/null -w 'prod_api:%{http_code}\\n' 'https://turbo-podbor.ru/podbor-api/api/hints/?state=start'",
    "curl -sk -o /dev/null -w 'prod_html:%{http_code}\\n' https://turbo-podbor.ru/podbor-chat/",
    "curl -sk -o /dev/null -w 'prod_js:%{http_code}\\n' https://turbo-podbor.ru/podbor-chat/static/js/main.91e2e0ec.js",
]
parts = []
for cmd in cmds:
    _, o, e = client.exec_command(cmd, timeout=30)
    parts.append(o.read().decode(errors='replace'))
client.close()
Path(__file__).parent.joinpath("_diag_out2.txt").write_text("".join(parts), encoding="utf-8")
print("".join(parts))

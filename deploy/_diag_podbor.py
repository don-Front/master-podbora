import os
from pathlib import Path

import paramiko

HOST = "80.78.245.56"
PASSWORD = os.environ.get("TKP_VPS_PASSWORD", "")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username="root", password=PASSWORD, timeout=20, allow_agent=False, look_for_keys=False)

cmds = [
    "curl -sk -o /dev/null -w 'prod_html:%{http_code} size:%{size_download}\\n' https://turbo-podbor.ru/podbor-chat/",
    "curl -sk -o /dev/null -w 'prod_js:%{http_code} size:%{size_download}\\n' https://turbo-podbor.ru/podbor-chat/static/js/main.c3df7bcc.js",
    "curl -sk -o /dev/null -w 'prod_css:%{http_code} size:%{size_download}\\n' https://turbo-podbor.ru/podbor-chat/static/css/main.303c557e.css",
    "curl -sk -o /dev/null -w 'prod_api:%{http_code}\\n' 'https://turbo-podbor.ru/podbor-api/api/hints/?state=start'",
    "curl -s -o /dev/null -w 'pc_html:%{http_code} size:%{size_download}\\n' http://193.105.37.142:10111/",
    "curl -s -o /dev/null -w 'pc_js:%{http_code} size:%{size_download}\\n' http://193.105.37.142:10111/static/js/main.c3df7bcc.js",
    "curl -s -o /dev/null -w 'pc_api:%{http_code}\\n' 'http://193.105.37.142:10112/api/hints/?state=start'",
    "grep -n podbor-chat /opt/turbo-podbor/nginx/nginx.conf | head -20",
    "curl -sk https://turbo-podbor.ru/podbor-chat/ | head -c 500",
]
out_path = Path(__file__).parent / "_diag_out.txt"
parts = []
for cmd in cmds:
    _, o, e = client.exec_command(cmd, timeout=60)
    parts.append(f"=== {cmd}\n{o.read().decode(errors='replace')}\n{e.read().decode(errors='replace')}\n")
client.close()
out_path.write_text("".join(parts), encoding="utf-8")
print("written", out_path)

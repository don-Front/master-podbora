import os, paramiko
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('31.128.47.176',username='root',password=os.environ['MASTER_VPS_PASSWORD'],timeout=25)
cmds=[
 'grep API_TOKEN /opt/turbo-podbor/main.py | head -3',
 'cat /etc/systemd/system/turbo-podbor.service 2>/dev/null',
 'tr "\0" "\n" < /proc/$(pgrep -f "uvicorn main:app" | head -1)/environ 2>/dev/null | grep API_TOKEN || true',
]
for cmd in cmds:
 print('===', cmd)
 _,o,e=c.exec_command(cmd)
 print(o.read().decode('utf-8','replace'))
c.close()

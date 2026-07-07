# -*- coding: utf-8 -*-
import os, paramiko
from pathlib import Path
ROOT = Path(__file__).resolve().parent
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('31.128.47.176', username='root', password=os.environ['MASTER_VPS_PASSWORD'], timeout=25)
for start,end,name in [(1280,1400,'estimate_tkp'),(1,80,'imports')]:
    _,o,_=c.exec_command(f"sed -n '{start},{end}p' /opt/turbo-podbor/main.py")
    (ROOT/f'_vps_main_{name}.txt').write_text(o.read().decode('utf-8','replace'), encoding='utf-8')
    print('wrote', name)
c.close()

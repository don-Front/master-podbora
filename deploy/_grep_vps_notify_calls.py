# -*- coding: utf-8 -*-
import os, paramiko
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('31.128.47.176', username='root', password=os.environ['MASTER_VPS_PASSWORD'], timeout=25)
for pat in ['notify_manager_price','notify_manager_tkp','send-price-inquiry','send-tkp-request','estimate-price','tkp-pdf']:
    _,o,_=c.exec_command(f"grep -rn '{pat}' /opt/turbo-podbor --include='*.py' | sed -n '1,30p'")
    out=o.read().decode('utf-8','replace').strip()
    if out: print('===',pat,'===\n',out,'\n')
c.close()

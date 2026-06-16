import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("80.78.245.56", username="root", password="DVPozOfj0DwPmoxT", timeout=20, allow_agent=False, look_for_keys=False)
_, o, _ = c.exec_command("docker exec turbo-podbor-app sed -n '419,460p' /app/tkp_pdf.py", timeout=30)
with open(r"C:\Users\userii1\Downloads\Andrey (подбор, потом удалю)\master-podbora\deploy\_vps_snippet.txt", "w", encoding="utf-8") as f:
    f.write(o.read().decode(errors="replace"))
c.close()
print("done")

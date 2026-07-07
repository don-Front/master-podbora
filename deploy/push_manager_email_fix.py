# -*- coding: utf-8 -*-
"""Деплой исправления маршрутизации email менеджеру на VPS FastAPI."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("MASTER_VPS_HOST", "31.128.47.176")
PASSWORD = os.environ.get("MASTER_VPS_PASSWORD", "")
REMOTE_DIR = "/opt/turbo-podbor"
MAIN = f"{REMOTE_DIR}/main.py"

OLD_BLOCK = """    result = estimate_from_request(payload)
    if result.status == "success":
        equipment_name = result.equipment_name or result.equipment_id
        try:
            notify_manager_price_inquiry(
                equipment_name=equipment_name,
                price=result.price_display,
                phone=(payload.phone or "").strip(),
                email=(payload.email or "").strip(),
                client_fio=(payload.fio or payload.name or "").strip(),
                source=SOURCE_CHATBOT,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось отправить уведомление менеджеру (estimate-price): %s", exc
            )
    return result"""

NEW_BLOCK = """    # Уведомление менеджеру о запросе цены — только через POST /api/send-price-inquiry
    # (после верификации email пользователя), не при каждом расчёте estimate-price.
    return estimate_from_request(payload)"""


def main() -> int:
    if not PASSWORD:
        print("Set MASTER_VPS_PASSWORD")
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username="root", password=PASSWORD, timeout=25, allow_agent=False, look_for_keys=False
    )
    sftp = client.open_sftp()

    local_mgr = ROOT / "manager_notifications.py"
    local_cfg = ROOT / "email_config.py"
    if not local_mgr.is_file():
        print(f"Missing {local_mgr}")
        return 1

    sftp.put(str(local_mgr), f"{REMOTE_DIR}/manager_notifications.py")
    if local_cfg.is_file():
        sftp.put(str(local_cfg), f"{REMOTE_DIR}/email_config.py")
    sftp.close()

    _, stdout, stderr = client.exec_command(f"python3 -c \"print(open('{MAIN}', encoding='utf-8').read().count('notify_manager_price_inquiry'))\"")
    count_before = stdout.read().decode().strip()
    print(f"notify_manager_price_inquiry refs before patch: {count_before}")

    patch_cmd = (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"path = Path('{MAIN}')\n"
        "text = path.read_text(encoding='utf-8')\n"
        f"old = {OLD_BLOCK!r}\n"
        f"new = {NEW_BLOCK!r}\n"
        "if old not in text:\n"
        "    raise SystemExit('estimate-price notify block not found in main.py')\n"
        "path.write_text(text.replace(old, new, 1), encoding='utf-8')\n"
        "print('main.py patched')\n"
        "PY"
    )
    _, stdout, stderr = client.exec_command(patch_cmd)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        print(err)
    print(out)
    if "patched" not in out:
        client.close()
        return 1

    _, stdout, _ = client.exec_command(
        f"grep -n 'MANAGER_EMAIL' {REMOTE_DIR}/manager_notifications.py {REMOTE_DIR}/email_config.py | sed -n '1,6p'"
    )
    print(stdout.read().decode("utf-8", "replace").strip())

    restart_cmds = [
        "systemctl restart turbo-podbor 2>/dev/null || true",
        "systemctl restart turbo-podbor.service 2>/dev/null || true",
        "pkill -f 'uvicorn.*main:app' 2>/dev/null || true",
        f"cd {REMOTE_DIR} && nohup uvicorn main:app --host 0.0.0.0 --port 8080 > /var/log/turbo-podbor.log 2>&1 &",
    ]
    for cmd in restart_cmds:
        client.exec_command(cmd)

    import time

    time.sleep(3)
    _, stdout, _ = client.exec_command(
        "curl -sS -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/estimate-price"
    )
    print("estimate-price GET:", stdout.read().decode().strip())

    client.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

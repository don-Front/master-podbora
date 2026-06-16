# -*- coding: utf-8 -*-
"""Патч main.py на VPS: коды верификации в файл (работает с несколькими uvicorn workers)."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = "80.78.245.56"
REMOTE_DIR = "/opt/turbo-podbor"
LOCAL_DIR = Path(__file__).resolve().parent
LOCAL_STORE = LOCAL_DIR / "verification_codes_store.py"
LOCAL_MAIN = LOCAL_DIR / "_main_from_vps.py"


def patch_main(text: str) -> str:
    marker = "from verification_codes_store import"
    if marker in text:
        return text

    text = text.replace(
        "# Хранилище кодов верификации email (в памяти)\n"
        "# Формат: {email: {\"code\": \"123456\", \"expires\": timestamp, \"verified\": False}}\n"
        "verification_codes: Dict[str, Dict[str, Any]] = {}\n"
        "VERIFICATION_CODE_TTL = 300  # 5 минут в секундах",
        "# Коды верификации — verification_codes_store.py (общий файл для всех workers)\n"
        "VERIFICATION_CODE_TTL = 300  # 5 минут в секундах\n"
        "from verification_codes_store import (\n"
        "    delete_entry as _vc_delete,\n"
        "    get_entry as _vc_get,\n"
        "    mark_verified as _vc_mark_verified,\n"
        "    purge_expired as _vc_purge,\n"
        "    set_code as _vc_set,\n"
        ")\n",
    )

    text = text.replace(
        "        # Сохраняем код\n"
        "        verification_codes[email] = {\n"
        '            "code": code,\n'
        '            "expires": expires,\n'
        '            "verified": False\n'
        "        }\n",
        "        # Сохраняем код (файл, доступен всем workers)\n"
        "        _vc_purge()\n"
        "        _vc_set(email, code, expires)\n",
    )

    text = text.replace(
        "        # Проверяем наличие кода для этого email\n"
        "        if email not in verification_codes:\n"
        "            return JSONResponse(\n"
        "                status_code=400,\n"
        '                content={"status": "error", "message": "Сначала запросите код"}\n'
        "            )\n"
        "        \n"
        "        stored = verification_codes[email]\n"
        "        \n"
        "        # Проверяем срок действия\n"
        "        if datetime.now().timestamp() > stored[\"expires\"]:\n"
        "            del verification_codes[email]\n",
        "        _vc_purge()\n"
        "        stored = _vc_get(email)\n"
        "        if not stored:\n"
        "            return JSONResponse(\n"
        "                status_code=400,\n"
        '                content={"status": "error", "message": "Сначала запросите код"}\n'
        "            )\n"
        "        \n"
        "        # Проверяем срок действия\n"
        "        if datetime.now().timestamp() > stored[\"expires\"]:\n"
        "            _vc_delete(email)\n",
    )

    text = text.replace(
        '        verification_codes[email]["verified"] = True',
        "        _vc_mark_verified(email)",
    )
    return text


def main() -> None:
    password = os.environ.get("TKP_VPS_PASSWORD", "")
    if not password:
        raise SystemExit("Set TKP_VPS_PASSWORD")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username="root", password=password, timeout=20, allow_agent=False, look_for_keys=False
    )
    sftp = client.open_sftp()

    sftp.get(f"{REMOTE_DIR}/main.py", str(LOCAL_MAIN))
    original = LOCAL_MAIN.read_text(encoding="utf-8")
    patched = patch_main(original)
    if patched == original:
        print("main.py: no changes (already patched?)")
    else:
        LOCAL_MAIN.write_text(patched, encoding="utf-8")
        sftp.put(str(LOCAL_MAIN), f"{REMOTE_DIR}/main.py")
        print("main.py: patched on host")

    sftp.put(str(LOCAL_STORE), f"{REMOTE_DIR}/verification_codes_store.py")

    cmds = [
        f"docker cp {REMOTE_DIR}/verification_codes_store.py turbo-podbor-app:/app/verification_codes_store.py",
        f"docker cp {REMOTE_DIR}/main.py turbo-podbor-app:/app/main.py",
        "docker exec turbo-podbor-app mkdir -p /app/data",
        "docker exec turbo-podbor-app rm -rf /app/__pycache__",
        f"sed -i 's/--workers\", \"4\"/--workers\", \"1\"/' {REMOTE_DIR}/Dockerfile",
        "docker restart turbo-podbor-app",
        "sleep 5",
        "docker exec turbo-podbor-app grep -n verification_codes_store /app/main.py | head -3",
        "docker exec turbo-podbor-app python3 -c \"import verification_codes_store as v; v.set_code('probe@test.ru','123456',9999999999); print('ok', v.get_entry('probe@test.ru')['code'])\"",
    ]
    for cmd in cmds:
        _, o, e = client.exec_command(cmd, timeout=180)
        out = o.read().decode(errors="replace").strip()
        err = e.read().decode(errors="replace").strip()
        if out:
            print(out[:400])
        if err:
            print("ERR:", err[:200])

    client.close()
    print("DONE")


if __name__ == "__main__":
    main()

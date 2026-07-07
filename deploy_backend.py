# -*- coding: utf-8 -*-
"""Деплой Django-бэкенда чатбота (Daphne :10112) на рабочей машине 192.168.5.53."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "back" / "chatbot"
HEALTH_URL = "http://127.0.0.1:10112/health/"
API_BASE = "http://127.0.0.1:10112"
PORT = 10112


def _log(msg: str) -> None:
    print(f"[deploy_backend] {msg}", flush=True)


def _find_listening_pid(port: int) -> int | None:
    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
    except subprocess.CalledProcessError:
        return None
    for line in out.splitlines():
        if f":{port}" not in line or "LISTENING" not in line:
            continue
        parts = line.split()
        if parts:
            try:
                return int(parts[-1])
            except ValueError:
                continue
    return None


def _stop_daphne() -> None:
    pid = _find_listening_pid(PORT)
    if not pid:
        _log(f"port {PORT}: nothing to stop")
        return
    _log(f"stop PID {pid} on :{PORT}")
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)


def _start_daphne() -> None:
    script = BACKEND_DIR / "run_daphne.ps1"
    if not script.is_file():
        raise FileNotFoundError(script)
    _log(f"start Daphne from {BACKEND_DIR}")
    subprocess.Popen(
        [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-NoProfile",
            "-File",
            str(script),
        ],
        cwd=str(BACKEND_DIR),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def _wait_health(timeout_sec: int = 90) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
                if resp.status == 200:
                    _log("health OK")
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2)
    raise RuntimeError(f"health check failed: {HEALTH_URL}")


def _migrate() -> None:
    _log("migrate")
    subprocess.run(
        ["py", "-3", "manage.py", "migrate", "--noinput"],
        cwd=str(BACKEND_DIR),
        check=True,
    )


def _verify_competitor_mask() -> None:
    create_req = urllib.request.Request(
        f"{API_BASE}/api/chats/",
        data=json.dumps({"title": "deploy-check"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chat = json.loads(urllib.request.urlopen(create_req, timeout=20).read())
    chat_id = chat["id"]
    payload = json.dumps(
        {
            "content": "РГ-Т-G163-DN100-PN16-О",
            "hint_state": "start",
            "hint_locked": False,
            "is_hint_selection": False,
        }
    ).encode()
    msg_req = urllib.request.Request(
        f"{API_BASE}/api/chats/{chat_id}/messages/",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(msg_req, timeout=60).read())
    bot = next(item for item in resp["messages"] if not item["is_user"])
    text = (bot.get("content") or "").strip()
    if text:
        raise RuntimeError(f"competitor mask check failed: expected empty bot text, got: {text[:200]!r}")
    card = resp.get("competitor_mask_card") or {}
    errors = card.get("errors") or []
    if card.get("is_valid") is not False or not errors:
        raise RuntimeError(f"competitor mask check failed, card={card!r}")
    if not any(str(item.get("raw_value")) == "G163" for item in errors):
        raise RuntimeError(f"competitor mask check failed, errors={errors!r}")
    _log("competitor mask route OK")


def main() -> int:
    os.chdir(BACKEND_DIR)
    _stop_daphne()
    time.sleep(2)
    _migrate()
    _start_daphne()
    _wait_health()
    _verify_competitor_mask()
    _log("done")
    _log(f"prod proxy: https://master-turbo-podbor.ru/podbor-api/health/")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _log(f"FAILED: {exc}")
        raise SystemExit(1)

# -*- coding: utf-8 -*-
"""Общее хранилище кодов верификации для нескольких uvicorn workers (файл + блокировка)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

try:
    import fcntl  # Unix
except ImportError:
    fcntl = None  # type: ignore

_DEFAULT_PATH = Path(os.environ.get("VERIFICATION_CODES_PATH", "/app/data/verification_codes.json"))


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _lock_file(fh) -> None:
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _unlock_file(fh) -> None:
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def load_all(path: Path | None = None) -> Dict[str, Dict[str, Any]]:
    p = path or _DEFAULT_PATH
    if not p.is_file():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            _lock_file(fh)
            try:
                raw = fh.read().strip()
            finally:
                _unlock_file(fh)
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_all(codes: Dict[str, Dict[str, Any]], path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
    _ensure_parent(p)
    tmp = p.with_suffix(".json.tmp")
    payload = json.dumps(codes, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as fh:
        _lock_file(fh)
        try:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            _unlock_file(fh)
    tmp.replace(p)


def set_code(email: str, code: str, expires: float, path: Path | None = None) -> None:
    em = email.strip().lower()
    codes = load_all(path)
    codes[em] = {"code": code, "expires": expires, "verified": False}
    save_all(codes, path)


def get_entry(email: str, path: Path | None = None) -> Dict[str, Any] | None:
    em = email.strip().lower()
    return load_all(path).get(em)


def delete_entry(email: str, path: Path | None = None) -> None:
    em = email.strip().lower()
    codes = load_all(path)
    if em in codes:
        del codes[em]
        save_all(codes, path)


def mark_verified(email: str, path: Path | None = None) -> None:
    em = email.strip().lower()
    codes = load_all(path)
    if em not in codes:
        return
    codes[em]["verified"] = True
    save_all(codes, path)


def purge_expired(path: Path | None = None) -> None:
    now = time.time()
    codes = load_all(path)
    changed = False
    for em, stored in list(codes.items()):
        if now > float(stored.get("expires") or 0):
            del codes[em]
            changed = True
    if changed:
        save_all(codes, path)

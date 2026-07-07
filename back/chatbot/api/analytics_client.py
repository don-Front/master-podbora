# -*- coding: utf-8 -*-
"""Клиент учёта обращений в аналитике (FastAPI /api/analytics/support-request)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional, Tuple

from django.conf import settings

logger = logging.getLogger(__name__)


def _support_request_url() -> str:
    url = getattr(
        settings,
        "ANALYTICS_SUPPORT_REQUEST_URL",
        "https://master-turbo-podbor.ru/api/analytics/support-request",
    )
    return url.rstrip("/")


def _api_token() -> str:
    return (
        getattr(settings, "ANALYTICS_API_TOKEN", "")
        or getattr(settings, "API_TOKEN", "")
        or "change-me"
    ).strip()


def record_support_request(
    *,
    email: str = "",
    phone: str = "",
    user_id: str = "",
    topic: str = "",
    channel: str = "chatbot",
    source: str = "chatbot",
) -> Tuple[bool, str]:
    """
    POST /api/analytics/support-request с Bearer-токеном.
    Нужен хотя бы один идентификатор: email, phone или user_id.
    """
    payload = {
        "email": (email or "").strip(),
        "phone": (phone or "").strip(),
        "user_id": (user_id or "").strip(),
        "topic": (topic or "").strip(),
        "channel": (channel or "chatbot").strip(),
        "source": (source or "chatbot").strip(),
    }
    if not any((payload["email"], payload["phone"], payload["user_id"])):
        return False, "Нет email, phone или user_id для аналитики"

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _support_request_url(),
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_token()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip() else {}
            if resp.status == 200 and body.get("status") == "success":
                return True, ""
            return False, body.get("message") or body.get("detail") or f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip() else {}
            err = body.get("detail") or body.get("message") or raw
        except Exception:
            err = str(exc)
        logger.warning("analytics support-request HTTP %s: %s", exc.code, err)
        return False, str(err)
    except Exception as exc:
        logger.warning("analytics support-request failed: %s", exc)
        return False, str(exc)

# -*- coding: utf-8 -*-
"""HTTP-клиент к сервису верификации почты (отдельный процесс, обычно :8001)."""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


def _origin():
    return getattr(settings, 'VERIFICATION_SERVICE_ORIGIN', 'http://127.0.0.1:8001').rstrip('/')


def _post_json(path: str, payload: dict, timeout: int = 20):
    url = f"{_origin()}{path}"
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            body = json.loads(raw) if raw.strip() else {}
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode('utf-8', errors='replace')
            body = json.loads(raw) if raw.strip() else {}
        except Exception:
            body = {}
        return e.code, body
    except Exception as e:
        logger.warning('verification request failed: %s %s', url, e)
        return 0, {'_error': str(e)}


def send_verification_code(email: str):
    """POST /api/send-verification-code — тело {"email": "..."}."""
    status, data = _post_json('/api/send-verification-code', {'email': email})
    if status == 200 and data.get('status') == 'success':
        return True, (data.get('message') or '').strip()
    err = (
        data.get('message')
        or data.get('error')
        or data.get('_error')
        or (f'HTTP {status}' if status else 'Сервис верификации недоступен')
    )
    return False, str(err)


def verify_code(email: str, code: str):
    """POST /api/verify-code — тело {"email": "...", "code": "..."}."""
    status, data = _post_json('/api/verify-code', {'email': email, 'code': code})
    if status == 200 and data.get('status') == 'success' and bool(data.get('verified')):
        return True, ''
    err = (
        data.get('message')
        or data.get('error')
        or data.get('_error')
        or (f'HTTP {status}' if status else 'Сервис верификации недоступен')
    )
    return False, str(err)

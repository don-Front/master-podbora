# -*- coding: utf-8 -*-
"""POST /api/submit-household-gas-request на сервисе VERIFICATION_SERVICE_ORIGIN (обычно :8010)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def submit_household_gas_url() -> str:
    full = (getattr(settings, 'SUBMIT_HOUSEHOLD_GAS_URL', None) or '').strip().rstrip('/')
    if full:
        return full
    origin = getattr(settings, 'VERIFICATION_SERVICE_ORIGIN', 'http://192.168.5.49:8010')
    return f"{str(origin).rstrip('/')}/api/submit-household-gas-request"


def _parse_http_response(r: requests.Response) -> Dict[str, Any]:
    try:
        out = r.json()
    except Exception:
        out = {'status': 'error', 'message': (r.text or '')[:500]}
    if not isinstance(out, dict):
        out = {'status': 'error', 'message': str(out)}
    if r.status_code and r.status_code >= 400:
        out.setdefault('status', 'error')
        detail = out.get('detail')
        if detail is not None and not (out.get('message') or '').strip():
            out['message'] = detail if isinstance(detail, str) else str(detail)
    out.setdefault('http_status', r.status_code)
    return out


def _hint_404(tried_urls: str) -> str:
    return (
        'HTTP 404: маршрут не найден. Частые причины: '
        '1) в окружении Django указан хост самого Django (например :8002), а не сервис 1С :8010 — '
        'проверьте VERIFICATION_SERVICE_ORIGIN и SUBMIT_HOUSEHOLD_GAS_URL; '
        '2) на сервисе :8010 ещё нет POST …/submit-household-gas-request — уточните путь у бэкенда 1С и задайте '
        'полный URL в SUBMIT_HOUSEHOLD_GAS_URL. '
        f'Пробовали: {tried_urls}'
    )


def submit_household_gas_request(
    *,
    fullname: str,
    contact: str,
    comment: str,
    organization: str,
    phone: str,
    email: str,
    selected_items: List[Dict[str, Any]],
    timeout: int = 120,
) -> Dict[str, Any]:
    payload = {
        'fullname': fullname or '',
        'contact': contact or '',
        'comment': comment or '',
        'organization': organization or '',
        'phone': phone or '',
        'email': email or '',
        'source': 'external-bot',
        'selected_items': selected_items or [],
    }
    url = submit_household_gas_url()
    try:
        logger.info(
            'submit_household_gas_request: method=POST url=%s body=%s',
            url,
            payload,
        )
        r = requests.post(url, json=payload, timeout=timeout)
        out = _parse_http_response(r)
        tried: List[Tuple[str, requests.Response]] = [(url, r)]

        # Некоторые сервисы отдают 404 без завершающего слэша, а с «/» — 200.
        if r.status_code == 404 and not url.endswith('/'):
            url_slash = f'{url.rstrip("/")}/'
            logger.info(
                'submit_household_gas_request: HTTP 404, retrying with trailing slash url=%s',
                url_slash,
            )
            r2 = requests.post(url_slash, json=payload, timeout=timeout)
            tried.append((url_slash, r2))
            r, out = r2, _parse_http_response(r2)

        if r.status_code == 404:
            out['message'] = _hint_404(', '.join(t for t, _ in tried))

        logger.info(
            'submit_household_gas_request: response status=%s body=%s',
            r.status_code,
            out,
        )
        return out
    except Exception as e:
        logger.warning('submit_household_gas_request failed: %s', e)
        return {'status': 'error', 'message': str(e)}

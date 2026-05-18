# -*- coding: utf-8 -*-
"""POST заявки по подобранной СПУ (газ) на фиксированный endpoint 1С."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Явный URL из техзадания: для этого сценария endpoint не переопределяем env-настройками.
SUBMIT_SPU_APPLICATION_URL_FALLBACK = 'http://192.168.5.49:8010/api/submit-spu-application'

def submit_spu_application_url() -> str:
    return SUBMIT_SPU_APPLICATION_URL_FALLBACK


def build_submit_spu_application_body(
    *,
    fullname: str,
    contact: str,
    comment: str,
    gas_spu_selection: Dict[str, Any],
) -> Dict[str, Any]:
    """JSON contract expected by /api/submit-spu-application."""
    selection = {}
    if isinstance(gas_spu_selection, dict):
        raw_selection = gas_spu_selection.get('_last_payload')
        if isinstance(raw_selection, dict) and raw_selection:
            selection = dict(raw_selection)
        else:
            skip_keys = {'step', 'extras', 'card_snapshot', '_last_payload', '_pending_payload'}
            selection = {
                key: value
                for key, value in gas_spu_selection.items()
                if key not in skip_keys and not str(key).startswith('_') and value not in (None, '')
            }
            extras = gas_spu_selection.get('extras')
            if isinstance(extras, dict):
                if extras.get('ps'):
                    selection['optional_ps_sensor'] = True
                if extras.get('setter'):
                    selection['optional_setter'] = extras.get('setter')
    return {
        'fullname': fullname or '',
        'contact': contact or '',
        'comment': comment or '',
        'source': 'my-bot',
        'selection': selection,
    }


def submit_spu_application_request(
    *,
    fullname: str,
    contact: str,
    comment: str,
    gas_spu_selection: Dict[str, Any],
    tz_file_path: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    url = submit_spu_application_url()
    body = build_submit_spu_application_body(
        fullname=fullname,
        contact=contact,
        comment=comment,
        gas_spu_selection=gas_spu_selection or {},
    )
    try:
        logger.info('submit_spu_application_request: method=POST url=%s body=%s', url, body)
        if tz_file_path:
            logger.info('submit_spu_application_request: tz_file_path ignored for JSON endpoint: %s', tz_file_path)
        r = requests.post(url, json=body, timeout=timeout)
        try:
            out = r.json()
        except Exception:
            out = {'status': 'error', 'message': (r.text or '')[:500]}
        if not isinstance(out, dict):
            out = {'status': 'error', 'message': str(out)}
        if r.status_code and r.status_code >= 400:
            out.setdefault('status', 'error')
        out.setdefault('http_status', r.status_code)
        out.setdefault(
            '_request',
            {
                'method': 'POST',
                'url': url,
                'body': body,
            },
        )
        logger.info('submit_spu_application_request: response status=%s body=%s', r.status_code, out)
        return out
    except Exception as e:
        logger.warning('submit_spu_application_request failed: %s', e)
        return {
            'status': 'error',
            'message': str(e),
            '_request': {
                'method': 'POST',
                'url': url,
                'body': body,
            },
        }

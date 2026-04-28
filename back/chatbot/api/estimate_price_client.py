# -*- coding: utf-8 -*-
"""Клиент сервиса ориентировочной цены (отдельный процесс, обычно :8010)."""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from django.conf import settings

from .order_specs_helpers import merge_draft

logger = logging.getLogger(__name__)


def _origin() -> str:
    return getattr(
        settings,
        'ESTIMATE_PRICE_SERVICE_ORIGIN',
        'http://127.0.0.1:8010',
    ).strip().rstrip('/')


def _post_json(path: str, payload: dict, timeout: int = 25) -> Tuple[int, dict]:
    url = f'{_origin()}{path}'
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
        logger.warning('estimate-price request failed: %s %s', url, e)
        return 0, {'_error': str(e)}


def _number_from_specs(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(value))
    if m:
        return float(m.group(1).replace(',', '.'))
    return None


def _json_number(value: float) -> Any:
    return int(value) if value == int(value) else value


def _accuracy_to_percent(accuracy_val: Any) -> Optional[float]:
    if accuracy_val is None or accuracy_val == '':
        return None
    if isinstance(accuracy_val, (int, float)):
        return float(accuracy_val)
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(accuracy_val))
    if m:
        return float(m.group(1).replace(',', '.'))
    return None


def build_estimate_body_from_draft(draft: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Собирает тело POST /api/estimate-price из черновика запроса цены.
    Без id прибора или обязательных параметров из итогового JSON запрос не формируем.
    """
    eq = draft.get('equipment') or {}
    eid = str(eq.get('id') or eq.get('equipment_id') or '').strip()
    if not eid:
        return None

    ename = (eq.get('name') or eq.get('model') or '').strip() or 'Оборудование'
    specs = merge_draft(draft.get('specs') or {})

    diameter = _number_from_specs(specs.get('diameter'))
    pressure_max = _number_from_specs(specs.get('pressure_max'))
    accuracy = _accuracy_to_percent(specs.get('accuracy'))

    if not diameter or not pressure_max or accuracy is None:
        logger.warning(
            'estimate-price body not built: missing specs diameter=%r pressure_max=%r accuracy=%r',
            specs.get('diameter'),
            specs.get('pressure_max'),
            specs.get('accuracy'),
        )
        return None

    return {
        'equipment': {'id': eid, 'name': ename},
        'dn': int(diameter),
        'pressure_max_mpa': _json_number(pressure_max),
        'accuracy_percent': _json_number(accuracy),
    }


def request_estimate_price(body: Dict[str, Any]) -> Tuple[bool, Any]:
    """POST /api/estimate-price. Успех: (True, dict ответа), иначе (False, текст ошибки)."""
    status, data = _post_json('/api/estimate-price', body)
    if status == 200 and data.get('status') == 'success':
        return True, data
    err = (
        data.get('message')
        or data.get('error')
        or data.get('_error')
        or (f'HTTP {status}' if status else 'Сервис расчёта недоступен')
    )
    return False, str(err)

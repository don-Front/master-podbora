# -*- coding: utf-8 -*-
"""Проверка заполненности полей спецификации и парсинг ответов пользователя."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, Dict, List

from .pdf_order_analysis import SPEC_KEYS, _normalize_specs

# Поля, которые считаем числовыми (в т.ч. 0 считается «не заполнено» до уточнения)
NUMERIC_KEYS = frozenset(
    {
        "flow_min",
        "flow_max",
        "pressure_min",
        "pressure_max",
        "temperature_min",
        "temperature_max",
        "diameter",
    }
)


def _is_placeholder_text(s: str) -> bool:
    """Текст считаем пустым: «не указано», n/a, одно тире и т.п."""
    t = s.strip().lower().rstrip(".,;:")
    if not t:
        return True
    if t == "0":
        return True
    if t in (
        "не указано",
        "неуказано",
        "не указан",
        "не указана",
        "неизвестно",
        "отсутствует",
        "n/a",
        "na",
        "нет",
        "-",
        "—",
        "–",
    ):
        return True
    return False


def is_value_missing(key: str, value: Any) -> bool:
    """Пусто: None, пустая строка, \"0\", число 0, строка «не указано» и аналоги."""
    if value is None:
        return True
    if isinstance(value, Decimal):
        try:
            return float(value) == 0.0
        except Exception:
            return True
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return True
        return value == 0
    if isinstance(value, str):
        return _is_placeholder_text(value)
    return False


def list_missing_fields(draft: Dict[str, Any]) -> List[str]:
    d = _normalize_specs(draft)
    return [k for k in SPEC_KEYS if is_value_missing(k, d.get(k))]


FIELD_PROMPTS: Dict[str, str] = {
    "medium": "Укажите среду измерения (например: gas — газ, liquid — жидкость). Одно слово или коротко.",
    "gas_type": "Укажите тип газа (например: природный газ, пропан и т.п.).",
    "flow_min": "Укажите минимальный расход (число), например: 10",
    "flow_max": "Укажите максимальный расход (число), например: 500",
    "flow_unit": "Укажите единицу расхода (например: м³/ч).",
    "pressure_min": "Укажите минимальное давление (число), например: 0.1",
    "pressure_max": "Укажите максимальное давление (число), например: 1.6",
    "pressure_unit": "Укажите единицу давления (например: МПа).",
    "temperature_min": "Укажите минимальную температуру (число °C), например: -40",
    "temperature_max": "Укажите максимальную температуру (число °C), например: 60",
    "temperature_unit": "Укажите единицу температуры (например: °C).",
    "accuracy": "Укажите точность / класс точности (например: 1-2%).",
    "diameter": "Укажите диаметр (число, например: 100).",
}


def format_prompt_for_field(key: str) -> str:
    return FIELD_PROMPTS.get(key, f"Укажите значение для поля «{key}».")


def _parse_number(text: str) -> float:
    t = text.strip().replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    if not m:
        raise ValueError("ожидалось число")
    return float(m.group(0))


def parse_field_value(key: str, text: str) -> Any:
    """Парсит одно поле из текста пользователя."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("пустой ввод")

    if key in NUMERIC_KEYS:
        v = _parse_number(raw)
        if abs(v - int(v)) < 1e-9:
            return int(v)
        return v

    # строковые поля
    return raw


def merge_draft(base: Dict[str, Any]) -> Dict[str, Any]:
    return _normalize_specs(base)


def _to_json_safe_scalar(v: Any) -> Any:
    """Значение для JSON (DRF) — без Decimal/numpy/NaN, иначе клиент и сериализация падают с 500."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        try:
            x = float(v)
        except Exception:
            return str(v)
        if math.isnan(x) or math.isinf(x):
            return None
        return int(x) if abs(x - int(x)) < 1e-9 else x
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return int(v) if abs(v - int(v)) < 1e-9 else v
    if isinstance(v, str):
        return v
    if hasattr(v, "item"):
        try:
            return _to_json_safe_scalar(v.item())
        except Exception:
            pass
    return str(v)


def specs_for_api_response(draft: Any) -> Dict[str, Any]:
    """Только SPEC_KEYS, типы безопасны для json / Response."""
    if not isinstance(draft, dict):
        return {k: None for k in SPEC_KEYS}
    base = _normalize_specs(draft)
    return {k: _to_json_safe_scalar(base.get(k)) for k in SPEC_KEYS}

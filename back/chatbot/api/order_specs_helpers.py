# -*- coding: utf-8 -*-
"""Проверка заполненности полей спецификации и парсинг ответов пользователя."""

from __future__ import annotations

import json
import logging
import math
import re
from decimal import Decimal
from typing import Any, Dict, List

from .pdf_order_analysis import SPEC_KEYS, _normalize_specs, _SPEC_LEGACY_ALIASES, normalize_accuracy_value

logger = logging.getLogger(__name__)

# Поля, которые считаем числовыми (в т.ч. 0 считается «не заполнено» до уточнения)
NUMERIC_KEYS = frozenset(
    {
        "flowMin",
        "flowMax",
        "pressureMin",
        "pressureMax",
        "tempMediumMin",
        "tempMediumMax",
        "tempAmbientMin",
        "tempAmbientMax",
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
    d = merge_draft(draft)
    return [k for k in SPEC_KEYS if is_value_missing(k, d.get(k))]


FIELD_PROMPTS: Dict[str, str] = {
    "medium": "Укажите среду измерения (например: gas — газ, liquid — жидкость). Одно слово или коротко.",
    "gas_type": "Укажите тип измеряемой среды (например: природный газ, жидкость и т.п.).",
    "flowMin": "Укажите минимальный расход (число), например: 10",
    "flowMax": "Укажите максимальный расход (число), например: 500",
    "flow_unit": "Укажите единицу расхода (например: ст.м³/ч).",
    "pressureMin": "Укажите минимальное давление (число), например: 0.1",
    "pressureMax": "Укажите максимальное давление (число), например: 1.6",
    "pressure_unit": "Укажите единицу давления (например: МПа).",
    "tempMediumMin": "Укажите мин. температуру рабочей среды (число), например: -10",
    "tempMediumMax": "Укажите макс. температуру рабочей среды (число), например: 22",
    "tempAmbientMin": "Укажите мин. температуру окружающей среды (число), например: -38",
    "tempAmbientMax": "Укажите макс. температуру окружающей среды (число), например: 50",
    "temperature_unit": "Укажите единицу температуры для всех температур (например: °C).",
    "accuracy": "Укажите точность / класс точности (например: 0,5% или А).",
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
    key = _SPEC_LEGACY_ALIASES.get(key, key)
    raw = (text or "").strip()
    if not raw:
        raise ValueError("пустой ввод")

    if key in NUMERIC_KEYS:
        v = _parse_number(raw)
        if abs(v - int(v)) < 1e-9:
            return int(v)
        return v
    if key == "accuracy":
        return normalize_accuracy_value(raw)

    if key == "medium":
        low = raw.strip().lower()
        if low in ("gas", "газ", "gaz"):
            return "gas"
        if low in ("liquid", "жидкость", "жидк", "fluid"):
            return "liquid"
        if low in ("unknown", "неизвестно", "не указано"):
            return "unknown"
        return raw

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


# Подпись кнопки подтверждения — должна совпадать с hints_tree и views
ORDER_SPECS_CONFIRM_HINT = "Подтвердить и подобрать оборудование"


FIELD_LABELS: Dict[str, str] = {
    "medium": "Среда измерения",
    "gas_type": "Тип измеряемой среды",
    "flowMin": "Минимальный расход",
    "flowMax": "Максимальный расход",
    "flow_unit": "Единица расхода",
    "pressureMin": "Минимальное давление",
    "pressureMax": "Максимальное давление",
    "pressure_unit": "Единица давления",
    "tempMediumMin": "Мин. температура раб. среды",
    "tempMediumMax": "Макс. температура раб. среды",
    "tempAmbientMin": "Мин. температура окр. среды",
    "tempAmbientMax": "Макс. температура окр. среды",
    "temperature_unit": "Единица температуры",
    "accuracy": "Точность / класс",
    "diameter": "Диаметр",
}

_MEDIUM_DISPLAY = {
    "gas": "газ",
    "liquid": "жидкость",
    "unknown": "не указано",
}


def _format_spec_display_value(key: str, value: Any, draft: Dict[str, Any] | None = None) -> str:
    if is_value_missing(key, value):
        return "—"
    if key == "medium":
        s = str(value).strip().lower()
        return _MEDIUM_DISPLAY.get(s, str(value))
    if key in NUMERIC_KEYS and isinstance(value, (int, float)):
        if key == "diameter":
            return f"{value} мм"
        if draft:
            if key in ("flowMin", "flowMax"):
                unit = draft.get("flow_unit")
                if not is_value_missing("flow_unit", unit):
                    return f"{value} {unit}"
            if key in ("pressureMin", "pressureMax"):
                unit = draft.get("pressure_unit")
                if not is_value_missing("pressure_unit", unit):
                    return f"{value} {unit}"
        return str(value)
    return str(value).strip()


ORDER_SPECS_REVIEW_TITLE = "Проверьте итоговые параметры спецификации:"


def build_order_specs_review_rows(draft: Dict[str, Any]) -> List[Dict[str, str]]:
    """Строки таблицы для UI подтверждения (ключ, подпись, значение)."""
    d = merge_draft(draft)
    rows: List[Dict[str, str]] = []
    for key in SPEC_KEYS:
        rows.append(
            {
                "key": key,
                "label": FIELD_LABELS.get(key, key),
                "value": _format_spec_display_value(key, d.get(key), d),
            }
        )
    return rows


def build_order_specs_preview(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Структура для фронта: заголовок, строки таблицы, подпись под кнопкой."""
    return {
        "review_title": ORDER_SPECS_REVIEW_TITLE,
        "review_rows": build_order_specs_review_rows(draft),
        "footer": f"Если всё верно — нажмите «{ORDER_SPECS_CONFIRM_HINT}».",
    }


def format_specs_summary_for_user(draft: Dict[str, Any]) -> str:
    """Краткий текст в БД; таблицу рисует фронт по order_specs_preview."""
    return build_order_specs_preview(draft)["footer"]


def safe_print_order_specs_final(draft) -> None:
    """Вывод итогового JSON в консоль; не должен ронять запрос при нестандартных типах."""
    try:
        safe = specs_for_api_response(draft)
        line = json.dumps(safe, ensure_ascii=False)
        msg = f"[ORDER_SPECS_FINAL] {line}"
        from .pdf_order_analysis import _safe_console_print

        _safe_console_print(msg)
        logger.warning(msg)
    except Exception as e:
        err = f"[ERROR] ORDER_SPECS_FINAL (print): {e}"
        try:
            from .pdf_order_analysis import _safe_console_print

            _safe_console_print(err)
        except Exception:
            pass
        logger.exception("ORDER_SPECS_FINAL failed")

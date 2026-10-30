# -*- coding: utf-8 -*-
"""Нормализация среды измерения (gas / liquid) из текста пользователя."""

from __future__ import annotations

import re
from typing import Any

MEDIUM_UNSUPPORTED_MESSAGE = (
    "Среди подбираемого оборудования доступны только среды «газ» и «жидкость». "
    "Укажите одну из них."
)

_LIQUID_MARKERS = (
    "жидк",
    "liquid",
    "fluid",
    "нефт",
    "масл",
    "вода",
    "water",
    "oil",
    "конденсат",
)

_GAS_MARKERS = (
    "газ",
    "gas",
    "gaz",
    "природн",
    "сжижен",
    "сжиж",
    "попутн",
    "метан",
    "methane",
    "пропан",
    "propane",
    "бутан",
    "butane",
    "азот",
    "nitrogen",
    "воздух",
    "air",
    "гелий",
    "helium",
    "углекисл",
    "lpg",
    "lng",
    "cng",
    "natural",
)


def _prepare_medium_text(text: str) -> str:
    return (text or "").strip().lower().replace("ё", "е")


def normalize_medium_from_user_text(text: str) -> str:
    """
    Распознать gas или liquid из свободного ввода пользователя.

    Raises:
        ValueError: пустой ввод или среда не газ и не жидкость.
    """
    s = _prepare_medium_text(text)
    if not s:
        raise ValueError("пустой ввод")

    if s in ("gas", "liquid"):
        return s
    if s in ("газ", "gaz"):
        return "gas"
    if s in ("жидкость", "жидк"):
        return "liquid"

    if any(marker in s for marker in _LIQUID_MARKERS):
        return "liquid"
    if any(marker in s for marker in _GAS_MARKERS) or re.search(r"\bгаз\b", s):
        return "gas"

    raise ValueError(MEDIUM_UNSUPPORTED_MESSAGE)


_GAS_FORMULA_RE = re.compile(
    r"^(?:ch4|c2h6|c3h8|c4h10|c5h12|co2|n2|ar|h2s|o2)(?:\s*\+\s*(?:ch4|c2h6|c3h8|co2|n2))?$",
    re.IGNORECASE,
)


def try_normalize_medium_value(value: Any) -> Any:
    """Мягкая нормализация для LLM/OCR: только gas, liquid или unknown."""
    if value is None:
        return None
    s = _prepare_medium_text(str(value))
    if not s:
        return None
    if s in ("gas", "liquid", "unknown"):
        return s
    if s in ("неизвестно", "не указано"):
        return "unknown"
    try:
        return normalize_medium_from_user_text(str(value))
    except ValueError:
        if _GAS_FORMULA_RE.match(s.replace(" ", "")):
            return "gas"
        if re.search(r"\bch\d|состав\s+газ", s):
            return "gas"
        return "unknown"

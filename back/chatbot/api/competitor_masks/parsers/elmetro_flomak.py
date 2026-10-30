"""Парсер кода заказа ЭЛМЕТРО-Фломак (Приложение А РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens, split_mask_tokens

_PREFIX = re.compile(
    r"^(?:ЭЛМЕТРО|ELMETRO)[\s\-]*(?:Фломак|FLOMAK)[\s\-]*",
    re.IGNORECASE,
)
_SENSOR_DN = re.compile(r"^([SFUVG])(\d{3})$", re.IGNORECASE)
_PRESSURE = re.compile(r"^[LNMEHRSTZ]$", re.IGNORECASE)
_ACCURACY = re.compile(r"^[EWAC]$", re.IGNORECASE)
_EX = re.compile(r"^Ex[BC]$", re.IGNORECASE)
_COMBINED_LEU = re.compile(r"^L(?P<accuracy>[EWAC])U$", re.IGNORECASE)


def _strip_prefix(text: str) -> list[str]:
    raw = (text or "").strip()
    raw = _PREFIX.sub("", raw)
    return split_mask_tokens(raw)


def _extract_tokens(text: str) -> dict[str, str]:
    if not re.search(r"(?:ЭЛМЕТРО|ELMETRO)[\s\-]*(?:Фломак|FLOMAK)", text or "", re.IGNORECASE):
        return {}

    found: dict[str, str] = {}
    for token in _strip_prefix(text):
        if "ex_protection" not in found and _EX.match(token):
            found["ex_protection"] = token[:2] + token[2].upper()
            continue
        if "sensor_type" not in found:
            sensor_match = _SENSOR_DN.match(token)
            if sensor_match:
                found["sensor_type"] = sensor_match.group(1).upper()
                found["dn"] = sensor_match.group(2)
                continue
        if "pressure" not in found or "accuracy" not in found:
            combined = _COMBINED_LEU.match(token)
            if combined:
                found["pressure"] = "L"
                found["accuracy"] = combined.group("accuracy").upper()
                continue
        if "pressure" not in found and _PRESSURE.match(token):
            found["pressure"] = token.upper()
            continue
        if "accuracy" not in found and _ACCURACY.match(token):
            found["accuracy"] = token.upper()
    return found


def parse_elmetro_flomak_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        ("ex_protection", "sensor_type", "dn", "pressure", "accuracy"),
    )

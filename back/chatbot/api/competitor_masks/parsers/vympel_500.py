"""Парсер маски «Вымпел-500» (Приложение А РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens, split_mask_tokens

_PRESSURE = re.compile(r"^([АAИI])(\d+)$", re.IGNORECASE)
_ACCURACY = re.compile(r"^(0[,.]3|0[,.]5|0[,.]7|1[,.]0|1[,.]5)$")
_BLOCKS = re.compile(r"^[12]$")
_LAYOUT = re.compile(r"^0[12]$")
_POWER = re.compile(r"^[АAСC]$", re.IGNORECASE)
_DN = re.compile(r"^(\d+)$")
_OPTIONAL = re.compile(
    r"^(ТП\d+|ТН\d+|ИБП|ИП|БИ|УИВК|G|МК|MK)$",
    re.IGNORECASE,
)


def _strip_prefix(text: str) -> list[str]:
    raw = (text or "").strip()
    raw = re.sub(r"^(?:Вымпел|Vympel)[\s\-]*500[\s\-]*", "", raw, flags=re.IGNORECASE)
    return split_mask_tokens(raw)


def _extract_tokens(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    if not re.search(r"(?:Вымпел|Vympel)[\s\-]*500", text or "", re.IGNORECASE):
        return found

    for token in _strip_prefix(text):
        if _OPTIONAL.search(token):
            continue
        if "dn" not in found and _DN.match(token):
            found["dn"] = token
            continue
        if "pressure" not in found and _PRESSURE.match(token):
            match = _PRESSURE.match(token)
            letter = "А" if match.group(1).upper() in {"A", "А"} else "И"
            found["pressure"] = f"{letter}{match.group(2)}"
            continue
        if "accuracy" not in found and _ACCURACY.match(token):
            found["accuracy"] = token.replace(",", ".")
            continue
        if "blocks" not in found and _BLOCKS.match(token):
            found["blocks"] = token
            continue
        if "channels" not in found:
            channel_match = re.match(r"^(\d+)[KКkк]$", token, re.IGNORECASE)
            if channel_match:
                found["channels"] = f"{channel_match.group(1)}К"
                continue
        if "layout" not in found and _LAYOUT.match(token):
            found["layout"] = token
            continue
        if "power_type" not in found and _POWER.match(token):
            upper = token.upper()
            found["power_type"] = "А" if upper in {"A", "А"} else "С"
    return found


def parse_vympel_500_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        ("dn", "pressure", "accuracy", "blocks", "channels", "layout", "power_type"),
    )

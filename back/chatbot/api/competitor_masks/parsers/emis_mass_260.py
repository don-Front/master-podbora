"""Парсер карты заказа ЭМИС-МАСС 260 (таблица 1.1 РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens

_PREFIX = re.compile(
    r"^(?:ЭМИС|EMIS)[\s\-]*(?:МАСС|MASS)[\s\-]*260[\s\-–]*",
    re.IGNORECASE,
)
_DN = re.compile(r"^(?P<dn>\d{3})(?P<body>К|K|Х|X)?$", re.IGNORECASE)
_EX = re.compile(
    r"^(?:Ex|0Ex|Exa|Extib|Extia|Extaib|Extaia|РВ|РО-РВ)$",
    re.IGNORECASE,
)
_PLACEMENT = re.compile(r"^(И|ВТ|Д|ДМ|ДХХ|ДМХХ)$", re.IGNORECASE)
_CALIBRATION = re.compile(r"^[ЖГ]$", re.IGNORECASE)
_PRESSURE = re.compile(r"^(?:1[,.]0|1[,.]6|2[,.]5|4[,.]0|6[,.]3|10|16|25)$")
_ACCURACY = re.compile(r"^0[,.](?:1|15|2|25|5)$")
_BODY = re.compile(r"^[КKХX]$", re.IGNORECASE)


def _split_tokens(text: str) -> list[str]:
    raw = _PREFIX.sub("", (text or "").strip())
    return [chunk.strip() for chunk in re.split(r"[\s\-–]+", raw) if chunk.strip()]


def _extract_tokens(text: str) -> dict[str, str]:
    if not re.search(r"(?:ЭМИС|EMIS)[\s\-]*(?:МАСС|MASS)[\s\-]*260", text or "", re.IGNORECASE):
        return {}

    found: dict[str, str] = {}
    for token in _split_tokens(text):
        if "ex_protection" not in found and _EX.match(token):
            upper = token.upper()
            found["ex_protection"] = "Ex" if upper == "EX" else upper
            continue
        if "dn" not in found:
            dn_match = _DN.match(token)
            if dn_match:
                found["dn"] = dn_match.group("dn")
                body = (dn_match.group("body") or "").upper()
                if body in {"K", "К"}:
                    found["body"] = "К"
                elif body in {"X", "Х"}:
                    found["body"] = "Х"
                continue
        if "body" not in found and _BODY.match(token):
            upper = token.upper()
            found["body"] = "К" if upper in {"K", "К"} else "Х"
            continue
        if "placement" not in found and _PLACEMENT.match(token):
            found["placement"] = token.upper()
            continue
        if "calibration" not in found and _CALIBRATION.match(token):
            found["calibration"] = token.upper()
            continue
        if "pressure" not in found and _PRESSURE.match(token):
            found["pressure"] = token.replace(".", ",")
            continue
        if "accuracy" not in found and _ACCURACY.match(token):
            found["accuracy"] = token.replace(".", ",")
    return found


def parse_emis_mass_260_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        ("ex_protection", "dn", "body", "placement", "calibration", "pressure", "accuracy"),
    )

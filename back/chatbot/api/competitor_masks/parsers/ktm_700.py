"""Парсер типового кода КТМ700 РУС (Приложение А РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens

_CODE = re.compile(
    r"(?:^|[\s\-])"
    r"(?P<layout>1P|2P|4P|8P|2Q|4Q)"
    r"(?P<material>\d{2})"
    r"(?P<dn>DN\d+)"
    r"(?P<pn>PN\d+)"
    r"(?P<flange>G[BCDEF][0-9])"
    r"(?P<removable>[SN])"
    r"(?P<pressure_tap>00|12|20|25|50)"
    r"(?P<built_in_pressure>[NY])",
    re.IGNORECASE,
)
_BOI = re.compile(r"(?P<boi>[FL][1-57])(?:N\d{2}|A|C[123])", re.IGNORECASE)
_TEMP = re.compile(r"(C[123])(?:[\s\-]|$)", re.IGNORECASE)


def _extract_tokens(text: str) -> dict[str, str]:
    normalized = (text or "").upper().replace("КТМ", "KTM")
    if "KTM700" not in normalized and "КТМ700" not in (text or "").upper():
        return {}

    match = _CODE.search(normalized)
    if not match:
        return {}

    found = {
        "layout": match.group("layout").upper(),
        "material": match.group("material"),
        "dn": match.group("dn").upper(),
        "pn": match.group("pn").upper(),
        "flange": match.group("flange").upper(),
        "removable": match.group("removable").upper(),
        "pressure_tap": match.group("pressure_tap"),
        "built_in_pressure": match.group("built_in_pressure").upper(),
    }

    boi_match = _BOI.search(normalized)
    if boi_match:
        found["boi"] = boi_match.group("boi").upper()

    temp_match = _TEMP.search(normalized)
    if temp_match:
        found["temp"] = temp_match.group(1).upper()

    return found


def parse_ktm_700_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        (
            "layout",
            "material",
            "dn",
            "pn",
            "flange",
            "removable",
            "pressure_tap",
            "built_in_pressure",
            "boi",
            "temp",
        ),
    )

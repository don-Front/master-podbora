"""Парсер типового кода КТМ600 РУС (Приложение А РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens

_CODE = re.compile(
    r"(?:^|[\s\-])"
    r"(?P<layout>2P|4P|2X)"
    r"(?P<material>01|02|03|XX)"
    r"(?P<dn>DN\d+)"
    r"(?P<pn>PN\d+)"
    r"(?P<length>L\d+)"
    r"(?P<flange>G[BCDEF][0-9])"
    r"(?P<tap>N|12|14)"
    r"(?:[\s\-]|$)",
    re.IGNORECASE,
)
_TRANSDUCER = re.compile(r"(?:^|[\s\-])(LX|NX|MX|SX)(?:[\s\-]|$)", re.IGNORECASE)
_IO = re.compile(r"DC[\s\-]?([1-5])(?:[\s\-]|$)", re.IGNORECASE)


def _extract_tokens(text: str) -> dict[str, str]:
    normalized = (text or "").upper().replace("КТМ", "KTM").replace(" ", " ")
    if "KTM600" not in normalized and "КТМ600" not in (text or "").upper():
        return {}

    match = _CODE.search(normalized)
    if not match:
        return {}

    found = {
        "layout": match.group("layout").upper(),
        "material": match.group("material").upper(),
        "dn": match.group("dn").upper(),
        "pn": match.group("pn").upper(),
        "length": match.group("length").upper(),
        "flange": match.group("flange").upper(),
        "tap": match.group("tap").upper(),
    }

    transducer = _TRANSDUCER.search(normalized)
    if transducer:
        found["transducer"] = transducer.group(1).upper()

    io_match = _IO.search(normalized)
    if io_match:
        found["io"] = f"DC{io_match.group(1)}"

    return found


def parse_ktm_600_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        ("layout", "material", "dn", "pn", "length", "flange", "tap", "transducer", "io"),
    )

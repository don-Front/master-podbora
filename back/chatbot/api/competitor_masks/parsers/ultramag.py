"""Парсер маски ULTRAMAG (п. 2.1.10 РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens, split_mask_tokens

_IVBS = {"Б", "B", "М", "M"}
_LAYOUT = {"А", "A", "Т", "T"}
_CHANNELS = {"PTZ", "TZ", "Z"}
_DN = re.compile(r"^(32|40|50|80|100|150|200|250|300)$")
_SIZE = re.compile(r"^G(\d+)$", re.IGNORECASE)
_RANGE = re.compile(r"^1:\d+$", re.IGNORECASE)
_ACCURACY = re.compile(r"^(0\.5|1|1\.5)$")
_PRESSURE = re.compile(r"^(1|1А|1A)$", re.IGNORECASE)
_DIRECTION = re.compile(r"^(П|Л|P|L)$", re.IGNORECASE)
_REV = re.compile(r"^R$", re.IGNORECASE)


def _extract_tokens(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    started = False
    for token in split_mask_tokens(text):
        upper = token.upper()
        if not started:
            if "ULTRAMAG" in upper:
                started = True
            continue
        if upper in {"СЯМИ", "407229", "722", "ТУ", "TU"} or upper.startswith("407229"):
            break
        if "ivb" not in found and upper in _IVBS:
            found["ivb"] = token
            continue
        if "layout" not in found and upper in _LAYOUT:
            found["layout"] = token
            continue
        if "channels" not in found and upper in _CHANNELS:
            found["channels"] = upper
            continue
        if "dn" not in found and _DN.match(token):
            found["dn"] = token
            continue
        if "size" not in found and _SIZE.match(token):
            found["size"] = f"G{_SIZE.match(token).group(1).upper()}"
            continue
        if "dynamic_range" not in found and _RANGE.match(token):
            found["dynamic_range"] = token.replace(" ", "")
            continue
        if "accuracy" not in found and _ACCURACY.match(token.replace(",", ".")):
            found["accuracy"] = token.replace(",", ".")
            continue
        if "pressure_channel" not in found and _PRESSURE.match(token):
            found["pressure_channel"] = token
            continue
        if "direction" not in found and _DIRECTION.match(token):
            found["direction"] = token
            continue
        if "reversible" not in found and _REV.match(token):
            found["reversible"] = upper
    return found


def parse_ultramag_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        (
            "ivb",
            "layout",
            "channels",
            "dn",
            "size",
            "dynamic_range",
            "accuracy",
            "pressure_channel",
            "direction",
            "reversible",
        ),
    )

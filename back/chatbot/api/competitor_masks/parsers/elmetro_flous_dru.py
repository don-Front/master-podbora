"""Парсер кода заказа ЭЛМЕТРО-Флоус (ДРУ) (Приложение А РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens, split_mask_tokens

_PREFIX = re.compile(
    r"^(?:ЭЛМЕТРО|ELMETRO)[\s\-]*(?:Флоус|FLOUS)(?:\s*\(ДРУ\))?[\s\.\-]*",
    re.IGNORECASE,
)
_CHANNELS = re.compile(r"^\.?(?P<channels>[124])$")
_BODY_DN = re.compile(r"^(?P<body>[CP])(?P<dn>\d{3})$", re.IGNORECASE)
_COMBINED_LEU = re.compile(r"^L(?P<accuracy>[EWAC])U$", re.IGNORECASE)
_COMBINED_BN = re.compile(r"^(?P<pressure>[BLSMEH])N$", re.IGNORECASE)
_PRESSURE = re.compile(r"^[BLSMEH]$", re.IGNORECASE)
_EX = re.compile(r"^Ex$", re.IGNORECASE)


def _strip_prefix(text: str) -> list[str]:
    raw = (text or "").strip()
    channel_match = re.search(
        r"(?:ЭЛМЕТРО|ELMETRO)[\s\-]*(?:Флоус|FLOUS)(?:\s*\(ДРУ\))?\.(?P<channels>[124])",
        raw,
        re.IGNORECASE,
    )
    channels = channel_match.group("channels") if channel_match else None
    raw = _PREFIX.sub("", raw)
    tokens = split_mask_tokens(raw)
    if channels and (not tokens or tokens[0] != channels):
        return [channels, *tokens]
    return tokens


def _extract_tokens(text: str) -> dict[str, str]:
    if not re.search(r"(?:ЭЛМЕТРО|ELMETRO)[\s\-]*(?:Флоус|FLOUS)", text or "", re.IGNORECASE):
        return {}

    found: dict[str, str] = {}
    for token in _strip_prefix(text):
        if "channels" not in found:
            channel_match = _CHANNELS.match(token)
            if channel_match:
                found["channels"] = channel_match.group("channels")
                continue
        if "ex_protection" not in found and _EX.match(token):
            found["ex_protection"] = "Ex"
            continue
        if "body" not in found:
            body_match = _BODY_DN.match(token)
            if body_match:
                found["body"] = body_match.group("body").upper()
                found["dn"] = body_match.group("dn")
                continue
        if "accuracy" not in found or "function" not in found:
            combined = re.match(r"^(?P<a>[ABCDF])(?P<b>[WI])$", token, re.IGNORECASE)
            if combined:
                found["accuracy"] = combined.group("a").upper()
                found["function"] = combined.group("b").upper()
                continue
        if "pressure" not in found:
            pressure_match = _COMBINED_BN.match(token)
            if pressure_match:
                found["pressure"] = pressure_match.group("pressure").upper()
                continue
            if _PRESSURE.match(token):
                found["pressure"] = token.upper()
    return found


def parse_elmetro_flous_dru_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        ("channels", "ex_protection", "body", "dn", "accuracy", "function", "pressure"),
    )

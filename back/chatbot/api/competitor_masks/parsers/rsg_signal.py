"""Парсер маски РСГ СИГНАЛ (п. 1.1 РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens, split_mask_tokens

_SIZE = re.compile(r"^G(\d+)$", re.IGNORECASE)
_PN = re.compile(r"^PN(\d+)$", re.IGNORECASE)
_DN = re.compile(r"^(\d+)$")
_ACCURACY = re.compile(r"^[123]$")
_BODY = re.compile(r"^[BSGbsg]$", re.IGNORECASE)
_SKIP = re.compile(r"^(РСГ|СИГНАЛ|SIGNAL|СЯМИ|ТУ|TU|407273)$", re.IGNORECASE)


def _extract_tokens(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for token in split_mask_tokens(text):
        if _SKIP.search(token):
            continue
        if _SIZE.match(token) and "size" not in found:
            found["size"] = token.upper()
            continue
        if _PN.match(token) and "pn" not in found:
            found["pn"] = token.upper()
            continue
        if _ACCURACY.match(token) and "accuracy_variant" not in found:
            found["accuracy_variant"] = token
            continue
        if _BODY.match(token) and "body" not in found:
            found["body"] = token.upper()
            continue
        if _DN.match(token) and "dn" not in found:
            found["dn"] = token
    return found


def parse_rsg_signal_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        ("dn", "size", "accuracy_variant", "pn", "body"),
    )

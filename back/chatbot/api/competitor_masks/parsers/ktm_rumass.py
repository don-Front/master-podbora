"""Парсер условного обозначения КТМ РуМАСС (таблица 2 РЭ)."""

from __future__ import annotations

import re
from typing import Any

from .common import parse_fields_from_tokens

_MASK = re.compile(
    r"(?:КТМ|KTM)\s*РуМАСС(?P<dn>\d{3})"
    r"-(?P<boi>[01])"
    r"-(?P<variant>[012])"
    r"-\d{3}"
    r"-(?P<placement>\d{2})"
    r"-(?P<accuracy>\d{2})"
    r"-(?P<gas_group>[01])"
    r"-(?P<remote>[01])",
    re.IGNORECASE,
)


def _extract_tokens(text: str) -> dict[str, str]:
    match = _MASK.search(text or "")
    if not match:
        return {}
    return {key: match.group(key) for key in match.groupdict()}


def parse_ktm_rumass_mask(text: str, catalog: dict[str, Any]):
    tokens = _extract_tokens(text)
    return parse_fields_from_tokens(
        text,
        catalog,
        tokens,
        ("dn", "boi", "variant", "placement", "accuracy", "gas_group", "remote"),
    )

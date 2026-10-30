# -*- coding: utf-8 -*-
"""Сборка query-параметров для GET /api/search-equipment."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from .medium_normalize import try_normalize_medium_value
from .order_specs_helpers import merge_draft

# Ключи, уходящие в URL (camelCase как в API :8010)
SEARCH_QUERY_KEYS = (
    "equipment_type",
    "medium",
    "application",
    "gas_type",
    "duplication_type",
    "flowMin",
    "flowMax",
    "flow_unit",
    "diameter",
    "pressureMin",
    "pressureMax",
    "pressure_unit",
    "tempMediumMin",
    "tempMediumMax",
    "temperature_unit",
    "tempAmbientMin",
    "tempAmbientMax",
    "accuracy",
)


def map_gas_type_to_api(gas_type: Any) -> str:
    s = str(gas_type or "").strip().lower()
    if "технолог" in s or s in ("technological", "tech"):
        return "technological"
    if "природ" in s or s in ("natural", "природный"):
        return "natural"
    return "natural"


def format_accuracy_for_api(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().replace(",", ".")
    s = s.replace("%", "").strip()
    if not s:
        return None
    m = re.search(r"\d+(?:\.\d+)?", s)
    return m.group(0) if m else s


def build_search_equipment_params(specs: Dict[str, Any]) -> Dict[str, str]:
    """Параметры GET /api/search-equipment из черновика спецификации."""
    s = merge_draft(specs)
    medium_raw = try_normalize_medium_value(s.get("medium"))
    medium = medium_raw if medium_raw in ("gas", "liquid") else "gas"
    params: Dict[str, str] = {
        "equipment_type": "flowmeters",
        "medium": medium,
        "application": "industrial",
        "gas_type": map_gas_type_to_api(s.get("gas_type")),
    }
    if medium == "gas":
        duplication_type = str(s.get("duplication_type") or "").strip()
        if duplication_type:
            params["duplication_type"] = duplication_type

    def add(key: str, val: Any) -> None:
        if val is None:
            return
        if isinstance(val, (int, float)):
            params[key] = str(int(val) if isinstance(val, float) and val == int(val) else val)
            return
        t = str(val).strip()
        if t:
            params[key] = t

    for key in (
        "flowMin",
        "flowMax",
        "flow_unit",
        "diameter",
        "pressureMin",
        "pressureMax",
        "pressure_unit",
        "tempMediumMin",
        "tempMediumMax",
        "temperature_unit",
        "tempAmbientMin",
        "tempAmbientMax",
    ):
        add(key, s.get(key))

    acc = format_accuracy_for_api(s.get("accuracy"))
    if acc:
        params["accuracy"] = acc

    return params


def build_search_equipment_url(base_url: str, specs: Dict[str, Any]) -> str:
    base = (base_url or "").strip().rstrip("/")
    qs = urlencode(build_search_equipment_params(specs), doseq=True)
    return f"{base}?{qs}"

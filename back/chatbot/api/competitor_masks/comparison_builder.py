"""Сборка карточки сравнения Turbo Flow UFG с конкурентом."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import yaml

from .catalog import get_catalog


def _comparison_yaml_path() -> str:
    current = os.path.abspath(__file__)
    project_root = os.path.normpath(os.path.join(os.path.dirname(current), "..", "..", "..", "project"))
    return os.path.join(project_root, "data", "competitors", "_comparison.yaml")


@lru_cache(maxsize=1)
def _load_comparison_data() -> dict[str, Any]:
    path = _comparison_yaml_path()
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def build_competitor_comparison_card(catalog_id: str) -> dict[str, Any] | None:
    """
    Сформировать payload flip-карточки «наши преимущества vs конкурент».

    Returns:
        dict для API или None, если для каталога нет данных сравнения.
    """
    catalog_key = str(catalog_id or "").strip()
    if not catalog_key:
        return None

    data = _load_comparison_data()
    comparisons = data.get("comparisons") or {}
    comparison = comparisons.get(catalog_key)
    if not isinstance(comparison, dict):
        return None

    catalog = get_catalog(catalog_key) or {}
    turbo_product = data.get("turbo_product") or {}
    rows = comparison.get("rows") or []
    if not rows:
        return None

    competitor_short = str(
        comparison.get("competitor_short")
        or catalog.get("competitor")
        or catalog_key,
    ).strip()

    return {
        "catalog_id": catalog_key,
        "title": "Преимуществ Turbo Flow UFG",
        "turbo_brand": str(turbo_product.get("brand") or 'НПО «Турбулентность-Дон»'),
        "turbo_product_name": str(turbo_product.get("product_name") or "Turbo Flow UFG-F-C"),
        "competitor_name": competitor_short,
        "competitor_full_name": str(catalog.get("competitor") or competitor_short),
        "rows": [
            {
                "label": str(row.get("label") or ""),
                "turbo_value": str(row.get("turbo") or ""),
                "competitor_value": str(row.get("competitor") or ""),
            }
            for row in rows
            if isinstance(row, dict) and row.get("label")
        ],
        "turbo_slide": {
            "title": str(turbo_product.get("title") or "Turbo Flow UFG-F-C"),
            "image_key": str(turbo_product.get("image_key") or "turbo_flow_ufg-f-c.png"),
            "highlights": [
                str(item).strip()
                for item in (turbo_product.get("highlights") or [])
                if str(item).strip()
            ],
        },
    }

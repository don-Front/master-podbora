"""Сборка JSON-карточки конкурента для фронтенда."""

from __future__ import annotations

from typing import Any

from .catalog import get_catalog
from .types import FieldValidationError, MaskDecodeResult, ParsedField


def _field_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = catalog.get("fields") or []
    return {str(item.get("id")): item for item in fields if isinstance(item, dict)}


def _build_parameters(
    parsed_fields: list[ParsedField],
    fields_cfg: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in parsed_fields:
        cfg = fields_cfg.get(field.field_id) or {}
        rows.append(
            {
                "field_id": field.field_id,
                "position": field.position,
                "label": field.label,
                "value": field.value,
                "hint": str(cfg.get("hint") or cfg.get("label") or field.label),
            }
        )
    rows.sort(key=lambda item: int(item.get("position") or 0))
    return rows


def _build_errors(errors: list[FieldValidationError]) -> list[dict[str, Any]]:
    return [
        {
            "field_id": err.field_id,
            "label": err.label,
            "raw_value": err.raw_value,
            "allowed": list(err.allowed),
        }
        for err in errors
    ]


def build_competitor_mask_card(result: MaskDecodeResult) -> dict[str, Any] | None:
    """Сформировать payload карточки для ответа API."""
    if not result.handled:
        return None

    catalog = get_catalog(result.catalog_id) or {}
    fields_cfg = _field_map(catalog)
    catalog_id = str(result.catalog_id or catalog.get("id") or "")

    return {
        "catalog_id": catalog_id,
        "competitor": result.competitor,
        "product_name": result.product_name,
        "image": str(catalog.get("image") or f"{catalog_id}.png"),
        "raw_mask": result.raw_mask,
        "is_valid": result.is_valid,
        "parameters": _build_parameters(result.parsed_fields, fields_cfg),
        "errors": _build_errors(result.errors),
        "source_document": result.source_document,
        "source_section": result.source_section,
    }

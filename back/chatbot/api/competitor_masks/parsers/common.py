"""Общие функции парсеров масок конкурентов."""

from __future__ import annotations

from typing import Any

from ..types import FieldValidationError, MaskDecodeResult, ParsedField


def field_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = catalog.get("fields") or []
    return {str(item.get("id")): item for item in fields if isinstance(item, dict)}


def normalize_token(raw: str, field_cfg: dict[str, Any]) -> str:
    aliases = field_cfg.get("aliases") or {}
    if raw in aliases:
        return str(aliases[raw])
    upper = raw.upper()
    if upper in aliases:
        return str(aliases[upper])

    if field_cfg.get("display_as_dn") and raw.isdigit():
        return f"DN{raw}"
    if field_cfg.get("id") == "size":
        value = raw.upper().lstrip("G")
        return f"G{value}"
    if field_cfg.get("id") == "pn":
        value = raw.upper().lstrip("PN")
        return f"PN{value}"
    if field_cfg.get("id") == "qmax" and raw.upper().startswith("G"):
        return raw.upper()
    if field_cfg.get("id") in {"body", "accuracy_variant", "dn", "pressure", "reversible"}:
        return raw.upper()
    return raw


def validate_field(
    field_id: str,
    raw_value: str,
    field_cfg: dict[str, Any],
    *,
    normalized: str,
) -> tuple[ParsedField | None, FieldValidationError | None]:
    label = str(field_cfg.get("label") or field_id)
    position = int(field_cfg.get("position") or 0)
    allowed = tuple(str(item) for item in (field_cfg.get("allowed") or []))

    if normalized in allowed:
        return (
            ParsedField(
                field_id=field_id,
                label=label,
                position=position,
                value=normalized,
            ),
            None,
        )

    return (
        None,
        FieldValidationError(
            field_id=field_id,
            label=label,
            raw_value=raw_value,
            allowed=allowed,
        ),
    )


def parse_fields_from_tokens(
    text: str,
    catalog: dict[str, Any],
    tokens: dict[str, str],
    field_order: tuple[str, ...],
) -> MaskDecodeResult:
    fields_cfg = field_map(catalog)
    parsed: list[ParsedField] = []
    errors: list[FieldValidationError] = []

    for field_id in field_order:
        raw_value = tokens.get(field_id)
        if not raw_value:
            continue
        field_cfg = fields_cfg.get(field_id)
        if not field_cfg:
            continue
        normalized = normalize_token(raw_value, field_cfg)
        ok_field, err = validate_field(field_id, raw_value, field_cfg, normalized=normalized)
        if ok_field:
            parsed.append(ok_field)
        if err:
            errors.append(err)

    parsed.sort(key=lambda item: item.position)
    return MaskDecodeResult(
        handled=True,
        catalog_id=str(catalog.get("id") or ""),
        competitor=str(catalog.get("competitor") or ""),
        product_name=str(catalog.get("product_name") or ""),
        source_document=str(catalog.get("source_document") or ""),
        source_section=str(catalog.get("source_section") or ""),
        parsed_fields=parsed,
        errors=errors,
        raw_mask=(text or "").strip(),
    )


def split_mask_tokens(text: str) -> list[str]:
    import re

    return [chunk for chunk in re.split(r"[\s\-/]+", (text or "").strip()) if chunk]

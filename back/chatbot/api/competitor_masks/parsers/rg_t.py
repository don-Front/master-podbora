"""Парсер маски счётчика РГ-Т (Приложение А РЭ)."""

from __future__ import annotations

import re
from typing import Any

from ..types import FieldValidationError, MaskDecodeResult, ParsedField

_SIZE_TOKEN = re.compile(r"^G(\d+)$", re.IGNORECASE)
_DN_TOKEN = re.compile(r"^DN(\d+)$", re.IGNORECASE)
_PN_TOKEN = re.compile(r"^PN(\d+)$", re.IGNORECASE)
_METROLOGY_TOKEN = re.compile(r"^(О|O|2У|2Y)$", re.IGNORECASE)


def _field_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = catalog.get("fields") or []
    return {str(item.get("id")): item for item in fields if isinstance(item, dict)}


def _normalize_metrology(raw: str, field_cfg: dict[str, Any]) -> str:
    aliases = field_cfg.get("aliases") or {}
    if raw in aliases:
        return str(aliases[raw])
    upper = raw.upper()
    if upper == "O":
        return "О"
    if upper == "2Y":
        return "2У"
    return raw


def _extract_tokens(text: str) -> dict[str, str]:
    """Извлечь сегменты маски из строки пользователя."""
    chunks = re.split(r"[\s\-/]+", (text or "").strip())
    tokens = [chunk for chunk in chunks if chunk]
    found: dict[str, str] = {}

    for token in tokens:
        if _SIZE_TOKEN.match(token) and "size" not in found:
            found["size"] = f"G{_SIZE_TOKEN.match(token).group(1).upper()}"  # type: ignore[union-attr]
            continue
        if _DN_TOKEN.match(token) and "dn" not in found:
            found["dn"] = f"DN{_DN_TOKEN.match(token).group(1)}"
            continue
        if _PN_TOKEN.match(token) and "pn" not in found:
            found["pn"] = f"PN{_PN_TOKEN.match(token).group(1)}"
            continue
        if _METROLOGY_TOKEN.match(token) and "metrology" not in found:
            found["metrology"] = token
    return found


def _validate_field(
    field_id: str,
    raw_value: str,
    field_cfg: dict[str, Any],
) -> tuple[ParsedField | None, FieldValidationError | None]:
    label = str(field_cfg.get("label") or field_id)
    position = int(field_cfg.get("position") or 0)
    allowed_raw = field_cfg.get("allowed") or []
    allowed = tuple(str(item) for item in allowed_raw)

    if field_id == "metrology":
        normalized = _normalize_metrology(raw_value, field_cfg)
    else:
        normalized = raw_value.upper()

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
            raw_value=raw_value.upper() if field_id != "metrology" else raw_value,
            allowed=allowed,
        ),
    )


def parse_rg_t_mask(text: str, catalog: dict[str, Any]) -> MaskDecodeResult:
    """Разобрать и провалидировать маску РГ-Т по whitelist из РЭ."""
    fields_cfg = _field_map(catalog)
    tokens = _extract_tokens(text)

    parsed: list[ParsedField] = []
    errors: list[FieldValidationError] = []

    for field_id in ("size", "dn", "pn", "metrology"):
        raw_value = tokens.get(field_id)
        if not raw_value:
            continue
        field_cfg = fields_cfg.get(field_id)
        if not field_cfg:
            continue
        ok_field, err = _validate_field(field_id, raw_value, field_cfg)
        if ok_field:
            parsed.append(ok_field)
        if err:
            errors.append(err)

    parsed.sort(key=lambda item: item.position)

    return MaskDecodeResult(
        handled=True,
        catalog_id=str(catalog.get("id") or "rg_t"),
        competitor=str(catalog.get("competitor") or "РГ-Т"),
        product_name=str(catalog.get("product_name") or ""),
        source_document=str(catalog.get("source_document") or ""),
        source_section=str(catalog.get("source_section") or ""),
        parsed_fields=parsed,
        errors=errors,
        raw_mask=(text or "").strip(),
    )

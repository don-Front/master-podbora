"""Маппинг распознанной маски конкурента → order_specs_json для search-equipment."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from ..pdf_order_analysis import _normalize_specs
from .catalog import get_catalog
from .types import ParsedField

logger = logging.getLogger(__name__)

ANALOG_INTRO = 'Рекомендуемые аналоги НПО «Турбулентность-Дон»'


@dataclass
class AnalogMappingResult:
    """Результат подготовки параметров подбора аналогов."""

    specs: dict[str, Any] | None = None
    intro: str = ANALOG_INTRO
    skip_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def _shared_analog_path() -> str:
    current = os.path.abspath(__file__)
    project_root = os.path.normpath(os.path.join(os.path.dirname(current), "..", "..", "..", "project"))
    return os.path.join(project_root, "data", "competitors", "_analog_shared.yaml")


def _load_shared_tables() -> dict[str, Any]:
    path = _shared_analog_path()
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _parsed_values(parsed_fields: list[ParsedField]) -> dict[str, str]:
    return {item.field_id: item.value for item in parsed_fields}


def _dn_to_mm(raw: str) -> int | float | None:
    text = str(raw or "").strip().upper()
    if not text:
        return None
    m = re.match(r"^DN(\d+)$", text)
    if m:
        return int(m.group(1))
    if text.isdigit():
        return int(text)
    return None


def _g_size_key(raw: str) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if text.startswith("G"):
        return f"G{text.lstrip('G')}" if text[1:].isdigit() else text
    m = re.match(r"^G(\d+)$", text, re.IGNORECASE)
    return f"G{m.group(1)}" if m else text


def _multiply(raw: str, factor: float) -> float | None:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return round(float(text) * factor, 4)
    except ValueError:
        return None


def _lookup(raw: str, table: dict[str, Any]) -> Any:
    key = str(raw or "").strip()
    if key in table:
        return table[key]
    upper = key.upper()
    for candidate, value in table.items():
        if str(candidate).upper() == upper:
            return value
    return None


def _pn_to_mpa(raw: str, shared: dict[str, Any]) -> float | None:
    key = str(raw or "").strip().upper()
    if not key.startswith("PN"):
        key = f"PN{key.lstrip('PN')}"
    table = shared.get("pn_mpa") or {}
    value = table.get(key)
    if value is not None:
        return float(value)
    m = re.match(r"^PN0*(\d+)$", key)
    if m:
        return round(int(m.group(1)) / 10.0, 4)
    return None


def _vympel_pressure_mpa(raw: str, shared: dict[str, Any]) -> float | None:
    text = str(raw or "").strip().upper()
    m = re.match(r"^([ИIAА])(\d+)$", text)
    if not m:
        return None
    factor = float(shared.get("vympel_pressure_factor") or 0.1)
    return round(int(m.group(2)) * factor, 4)


def _direct_numeric(raw: str) -> float | int | None:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None
    if text.upper().startswith("G") and text[1:].isdigit():
        return int(text[1:])
    try:
        num = float(text)
        return int(num) if num == int(num) else num
    except ValueError:
        return None


def _g_size_qmax(raw: str, shared: dict[str, Any]) -> float | int | None:
    key = _g_size_key(raw)
    table = shared.get("g_size_qmax") or {}
    value = table.get(key)
    if value is not None:
        return value
    m = re.match(r"^G(\d+)$", key)
    if m:
        return int(m.group(1))
    return None


def _irvis_qmax(raw: str, shared: dict[str, Any]) -> float | int | None:
    key = str(raw or "").strip().upper()
    table = shared.get("irvis_qmax") or {}
    if key in table:
        return table[key]
    if key.startswith("G") and key[1:].isdigit():
        return int(key[1:])
    return _direct_numeric(raw)


def _build_specs_for_catalog(
    catalog_id: str,
    parsed_fields: list[ParsedField],
) -> AnalogMappingResult:
    catalog = get_catalog(catalog_id) or {}
    mapping = catalog.get("analog_mapping") or {}
    if not mapping.get("enabled"):
        return AnalogMappingResult(skip_reason="analog_mapping_disabled")

    shared = _load_shared_tables()
    defaults = {**(shared.get("default_gas_specs") or {}), **(mapping.get("defaults") or {})}
    specs: dict[str, Any] = dict(defaults)
    values = _parsed_values(parsed_fields)
    warnings: list[str] = []

    builders = {
        "irvis_ultra": _map_irvis_ultra,
        "rg_t": _map_rg_t,
        "rsg_signal": _map_rsg_signal,
        "ultramag": _map_ultramag,
        "vympel_500": _map_vympel_500,
        "ktm_600": _map_ktm_600,
        "ktm_700": _map_ktm_700,
        "ktm_rumass": _map_ktm_rumass,
        "elmetro_flomak": _map_elmetro_flomak,
        "elmetro_flous_dru": _map_elmetro_flous_dru,
        "emis_mass_260": _map_emis_mass_260,
    }
    builder = builders.get(catalog_id)
    if not builder:
        return AnalogMappingResult(skip_reason=f"no_builder_for_{catalog_id}")

    builder(values, specs, shared, warnings)

    min_required = mapping.get("min_required_fields") or []
    for field_id in min_required:
        if field_id not in values or not str(values[field_id]).strip():
            return AnalogMappingResult(
                skip_reason=f"missing_required_field_{field_id}",
                warnings=warnings,
            )

    normalized = _normalize_specs(specs)
    if not normalized.get("flowMax") and not normalized.get("diameter"):
        return AnalogMappingResult(skip_reason="insufficient_search_params", warnings=warnings)

    return AnalogMappingResult(specs=normalized, warnings=warnings)


def _map_irvis_ultra(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("pressure"):
        mpa = _multiply(values["pressure"], 0.1)
        if mpa is not None:
            specs["pressureMax"] = mpa
    if values.get("dn"):
        dn = _dn_to_mm(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("qmax"):
        flow = _irvis_qmax(values["qmax"], shared)
        if flow is not None:
            specs["flowMax"] = flow
    if values.get("accuracy"):
        acc = _lookup(values["accuracy"], shared.get("irvis_accuracy") or {})
        if acc is not None:
            specs["accuracy"] = acc
        else:
            warnings.append("accuracy_not_mapped")


def _map_rg_t(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("size"):
        flow = _g_size_qmax(values["size"], shared)
        if flow is not None:
            specs["flowMax"] = flow
    if values.get("dn"):
        dn = _dn_to_mm(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("pn"):
        mpa = _pn_to_mpa(values["pn"], shared)
        if mpa is not None:
            specs["pressureMax"] = mpa
    if values.get("metrology"):
        acc = _lookup(values["metrology"], shared.get("rg_t_metrology") or {})
        if acc is not None:
            specs["accuracy"] = acc


def _map_rsg_signal(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("size"):
        flow = _g_size_qmax(values["size"], shared)
        if flow is not None:
            specs["flowMax"] = flow
    if values.get("dn"):
        dn = _dn_to_mm(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("pn"):
        mpa = _pn_to_mpa(values["pn"], shared)
        if mpa is not None:
            specs["pressureMax"] = mpa
    if values.get("accuracy_variant"):
        acc = _lookup(values["accuracy_variant"], shared.get("rsg_accuracy_variant") or {})
        if acc is not None:
            specs["accuracy"] = acc


def _map_ultramag(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("size"):
        flow = _g_size_qmax(values["size"], shared)
        if flow is not None:
            specs["flowMax"] = flow
    if values.get("dn"):
        dn = _direct_numeric(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("accuracy"):
        acc = _direct_numeric(values["accuracy"])
        if acc is not None:
            specs["accuracy"] = str(acc)
    specs["pressureMax"] = 1.6


def _map_vympel_500(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("dn"):
        dn = _direct_numeric(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("pressure"):
        mpa = _vympel_pressure_mpa(values["pressure"], shared)
        if mpa is not None:
            specs["pressureMax"] = mpa
    if values.get("accuracy"):
        acc = _direct_numeric(values["accuracy"])
        if acc is not None:
            specs["accuracy"] = str(acc)


def _map_ktm_600(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("dn"):
        dn = _dn_to_mm(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("pn"):
        mpa = _pn_to_mpa(values["pn"], shared)
        if mpa is not None:
            specs["pressureMax"] = mpa
    if values.get("size"):
        flow = _g_size_qmax(values["size"], shared)
        if flow is not None:
            specs["flowMax"] = flow


def _map_ktm_700(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    _map_ktm_600(values, specs, shared, warnings)


def _map_ktm_rumass(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("dn"):
        dn = _direct_numeric(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("accuracy"):
        acc = _lookup(values["accuracy"], shared.get("ktm_rumass_accuracy") or {})
        if acc is not None:
            specs["accuracy"] = str(acc)


def _map_elmetro_flomak(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("dn"):
        dn = _direct_numeric(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("pressure"):
        mpa = _lookup(values["pressure"], shared.get("elmetro_flomak_pressure_mpa") or {})
        if mpa is not None:
            specs["pressureMax"] = float(mpa)
    if values.get("accuracy"):
        acc = _lookup(values["accuracy"], shared.get("elmetro_flomak_accuracy") or {})
        if acc is not None:
            specs["accuracy"] = str(acc)


def _map_elmetro_flous_dru(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("dn"):
        dn = _direct_numeric(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("pressure"):
        mpa = _lookup(values["pressure"], shared.get("elmetro_flous_pressure_mpa") or {})
        if mpa is not None:
            specs["pressureMax"] = float(mpa)
    if values.get("accuracy"):
        acc = _lookup(values["accuracy"], shared.get("elmetro_flous_accuracy") or {})
        if acc is not None:
            specs["accuracy"] = str(acc)


def _map_emis_mass_260(
    values: dict[str, str],
    specs: dict[str, Any],
    shared: dict[str, Any],
    warnings: list[str],
) -> None:
    if values.get("dn"):
        dn = _direct_numeric(values["dn"])
        if dn is not None:
            specs["diameter"] = dn
    if values.get("pressure"):
        mpa = _direct_numeric(values["pressure"].replace(",", "."))
        if mpa is not None:
            specs["pressureMax"] = float(mpa)
    if values.get("accuracy"):
        acc = _direct_numeric(values["accuracy"].replace(",", "."))
        if acc is not None:
            specs["accuracy"] = str(acc)


def build_analog_search_specs(
    catalog_id: str,
    parsed_fields: list[ParsedField],
    *,
    is_valid: bool,
) -> AnalogMappingResult:
    """
    Подготовить order_specs_json для GET /api/search-equipment.

    Аналоги показываем только при полностью валидной маске.
    """
    if not is_valid:
        return AnalogMappingResult(skip_reason="mask_has_validation_errors")

    result = _build_specs_for_catalog(catalog_id, parsed_fields)
    if result.specs:
        logger.info(
            "Competitor analog specs catalog=%s flowMax=%s diameter=%s pressureMax=%s accuracy=%s warnings=%s",
            catalog_id,
            result.specs.get("flowMax"),
            result.specs.get("diameter"),
            result.specs.get("pressureMax"),
            result.specs.get("accuracy"),
            result.warnings,
        )
    else:
        logger.info(
            "Competitor analog skipped catalog=%s reason=%s",
            catalog_id,
            result.skip_reason,
        )
    return result

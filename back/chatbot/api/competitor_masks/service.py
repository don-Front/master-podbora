"""Оркестрация расшифровки масок конкурентов."""

from __future__ import annotations

import logging
from typing import Callable

from .catalog import get_catalog
from .detect import detect_catalog_id, looks_like_competitor_mask
from .parsers.irvis_ultra import parse_irvis_ultra_mask
from .parsers.ktm_600 import parse_ktm_600_mask
from .parsers.rg_t import parse_rg_t_mask
from .parsers.rsg_signal import parse_rsg_signal_mask
from .parsers.ultramag import parse_ultramag_mask
from .parsers.vympel_500 import parse_vympel_500_mask
from .types import MaskDecodeResult

logger = logging.getLogger(__name__)

PARSERS: dict[str, Callable[..., MaskDecodeResult]] = {
    "rg_t": parse_rg_t_mask,
    "rsg_signal": parse_rsg_signal_mask,
    "irvis_ultra": parse_irvis_ultra_mask,
    "ultramag": parse_ultramag_mask,
    "vympel_500": parse_vympel_500_mask,
    "ktm_600": parse_ktm_600_mask,
}


def _format_allowed_values(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def format_decode_response(result: MaskDecodeResult) -> str:
    """Сформировать текст ответа пользователю."""
    lines: list[str] = [
        f"Оборудование конкурента: {result.competitor}",
        result.product_name,
        "",
        f"Маска: {result.raw_mask}",
    ]

    if result.errors:
        lines.extend(
            [
                "",
                "В РЭ нет указанных значений для следующих параметров:",
            ]
        )
        for err in result.errors:
            lines.append(
                f"• [{err.label}]: «{err.raw_value}» — такого значения нет в РЭ. "
                f"Допустимые варианты: {_format_allowed_values(err.allowed)}."
            )

    if result.parsed_fields:
        lines.extend(["", "Расшифровка параметров по РЭ:"])
        for field in result.parsed_fields:
            lines.append(f"• [{field.position}] {field.label}: {field.value}")

    if result.source_document:
        source = result.source_document
        if result.source_section:
            source = f"{source}, {result.source_section}"
        lines.extend(["", f"Источник: {source}"])

    if result.is_valid:
        lines.extend(
            [
                "",
                "Все распознанные сегменты маски соответствуют допустимым значениям из РЭ.",
            ]
        )

    return "\n".join(lines)


class CompetitorMaskDecoder:
    """Сервис расшифровки масок конкурентов."""

    def looks_like_mask(self, text: str) -> bool:
        return looks_like_competitor_mask(text)

    def decode(self, text: str) -> MaskDecodeResult:
        catalog_id = detect_catalog_id(text)
        if not catalog_id:
            return MaskDecodeResult(handled=False)

        catalog = get_catalog(catalog_id)
        parser = PARSERS.get(catalog_id)
        if not catalog or not parser:
            logger.warning("Competitor catalog/parser missing for %s", catalog_id)
            return MaskDecodeResult(handled=False)

        result = parser(text, catalog)
        logger.info(
            "Competitor mask decode catalog=%s valid=%s errors=%s fields=%s",
            catalog_id,
            result.is_valid,
            [err.raw_value for err in result.errors],
            [field.value for field in result.parsed_fields],
        )
        return result


competitor_mask_decoder = CompetitorMaskDecoder()

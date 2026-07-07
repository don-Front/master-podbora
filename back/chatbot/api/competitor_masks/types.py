"""Типы результата расшифровки масок конкурентов."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldValidationError:
    """Ошибка валидации одного сегмента маски."""

    field_id: str
    label: str
    raw_value: str
    allowed: tuple[str, ...]


@dataclass(frozen=True)
class ParsedField:
    """Успешно распознанный и валидный сегмент маски."""

    field_id: str
    label: str
    position: int
    value: str


@dataclass
class MaskDecodeResult:
    """Результат попытки расшифровки маски."""

    handled: bool
    catalog_id: str = ""
    competitor: str = ""
    product_name: str = ""
    source_document: str = ""
    source_section: str = ""
    parsed_fields: list[ParsedField] = field(default_factory=list)
    errors: list[FieldValidationError] = field(default_factory=list)
    raw_mask: str = ""

    @property
    def is_valid(self) -> bool:
        return self.handled and not self.errors

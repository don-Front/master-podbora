"""Проверка доступности чанков по ключу документа базы знаний."""

from __future__ import annotations

from typing import Optional, Set

CATALOG_SITE_KEY = "catalog:site"


def chunk_document_key(chunk: dict) -> str:
    """Стабильный ключ источника для фильтрации активных документов."""
    meta = chunk.get("metadata") or {}
    explicit = (meta.get("knowledge_doc_key") or "").strip()
    if explicit:
        return explicit

    source_file = (meta.get("source_file") or "").strip()
    doc_type = (meta.get("doc_type") or meta.get("type") or "catalog").strip()

    if source_file:
        return f"{doc_type}:{source_file}"

    if chunk.get("product_url"):
        return CATALOG_SITE_KEY

    return CATALOG_SITE_KEY


def is_chunk_searchable(chunk: dict, active_keys: Optional[Set[str]]) -> bool:
    """None active_keys — фильтр отключён (все чанки доступны)."""
    if active_keys is None:
        return True
    return chunk_document_key(chunk) in active_keys

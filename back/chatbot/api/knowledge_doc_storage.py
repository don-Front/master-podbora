# -*- coding: utf-8 -*-
"""Поиск файлов документов базы знаний по knowledge_doc_key."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)


def _documents_root() -> Path:
    return Path(settings.BASE_DIR).parent / "project" / "data" / "documents"


def resolve_knowledge_document_path(document_key: str) -> Optional[Path]:
    """
    Возвращает путь к PDF/файлу по ключу вида passport:имя.pdf.
    Сначала source_path из KnowledgeDocument, затем каталог data/documents.
    """
    key = (document_key or "").strip()
    if not key or key == "catalog:site":
        return None

    try:
        from ..models import KnowledgeDocument

        row = KnowledgeDocument.objects.filter(document_key=key).first()
        if row and row.source_path:
            candidate = Path(row.source_path)
            if candidate.is_file():
                return candidate
    except Exception as exc:
        logger.debug("KnowledgeDocument lookup failed for %s: %s", key, exc)

    filename = key.split(":", 1)[-1].strip() if ":" in key else key
    doc_type = key.split(":", 1)[0].strip() if ":" in key else "passport"
    if not filename:
        return None

    root = _documents_root()
    direct_candidates = [
        root / doc_type / filename,
        root / "passport" / filename,
        root / "gost" / filename,
        root / "catalog" / filename,
    ]
    for path in direct_candidates:
        if path.is_file():
            return path

    target = filename.casefold()
    if root.is_dir():
        for path in root.rglob("*"):
            if path.is_file() and path.name.casefold() == target:
                return path

    return None

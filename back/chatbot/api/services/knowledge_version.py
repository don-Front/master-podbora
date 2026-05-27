"""Версионирование документов базы знаний и фильтрация чанков при поиске."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional

from django.db import transaction
from django.utils import timezone

from ..chatbot_core.chunk_access import CATALOG_SITE_KEY, chunk_document_key
from ..models import KnowledgeDocument

logger = logging.getLogger(__name__)

_HASH_CHUNK_SIZE = 1024 * 1024


class KnowledgeVersionService:
    @staticmethod
    def compute_file_hash(file_path: str | Path) -> str:
        """SHA-256 содержимого файла."""
        path = Path(file_path)
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                block = fh.read(_HASH_CHUNK_SIZE)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def get_active_document_keys() -> FrozenSet[str]:
        keys = KnowledgeDocument.objects.filter(is_active=True).values_list(
            "document_key", flat=True
        )
        return frozenset(keys)

    @staticmethod
    def register_document(
        *,
        document_key: str,
        display_name: str,
        doc_type: str,
        file_path: str | Path | None = None,
        file_hash: str | None = None,
        is_active: bool = True,
    ) -> KnowledgeDocument:
        """
        Регистрирует или обновляет документ.
        При смене хеша увеличивает version.
        """
        if file_path is not None and not file_hash:
            file_hash = KnowledgeVersionService.compute_file_hash(file_path)

        file_hash = file_hash or ""
        source_path = str(file_path) if file_path is not None else ""

        with transaction.atomic():
            obj = KnowledgeDocument.objects.filter(document_key=document_key).first()
            if obj is None:
                return KnowledgeDocument.objects.create(
                    document_key=document_key,
                    display_name=display_name,
                    doc_type=doc_type,
                    file_hash=file_hash,
                    version=1,
                    source_path=source_path,
                    is_active=is_active,
                )

            changed = False
            if obj.file_hash and file_hash and obj.file_hash != file_hash:
                obj.version += 1
                obj.file_hash = file_hash
                changed = True
            elif file_hash and not obj.file_hash:
                obj.file_hash = file_hash
                changed = True

            if display_name and obj.display_name != display_name:
                obj.display_name = display_name
                changed = True
            if doc_type and obj.doc_type != doc_type:
                obj.doc_type = doc_type
                changed = True
            if source_path and obj.source_path != source_path:
                obj.source_path = source_path
                changed = True
            if obj.is_active != is_active:
                obj.is_active = is_active
                changed = True

            if changed:
                obj.save()
            return obj

    @staticmethod
    def deactivate_document(document_key: str) -> bool:
        updated = KnowledgeDocument.objects.filter(document_key=document_key).update(
            is_active=False,
            updated_at=timezone.now(),
        )
        return updated > 0

    @staticmethod
    def activate_document(document_key: str) -> bool:
        updated = KnowledgeDocument.objects.filter(document_key=document_key).update(
            is_active=True,
            updated_at=timezone.now(),
        )
        return updated > 0

    @staticmethod
    def _registry_entry_for_key(key: str, chunks: List[dict]) -> Dict[str, str]:
        """display_name и doc_type по первому чанку с данным ключом."""
        sample = next((c for c in chunks if chunk_document_key(c) == key), None)
        if sample:
            meta = sample.get("metadata") or {}
            return {
                "display_name": (meta.get("document_name") or key)[:512],
                "doc_type": meta.get("doc_type") or KnowledgeDocument.DOC_TYPE_CATALOG,
            }
        if key == CATALOG_SITE_KEY:
            return {
                "display_name": "Каталог turbo-don.ru",
                "doc_type": KnowledgeDocument.DOC_TYPE_CATALOG,
            }
        return {"display_name": key[:512], "doc_type": KnowledgeDocument.DOC_TYPE_CATALOG}

    @classmethod
    def ensure_synced_from_chunks(cls, chunks: Iterable[dict]) -> int:
        """
        Создаёт записи KnowledgeDocument для всех ключей из chunks.json.
        Не деактивирует существующие документы — только upsert недостающих.
        """
        chunk_list = list(chunks)
        keys = {chunk_document_key(c) for c in chunk_list}
        if not keys:
            keys.add(CATALOG_SITE_KEY)

        created = 0
        for key in sorted(keys):
            if KnowledgeDocument.objects.filter(document_key=key).exists():
                continue
            info = cls._registry_entry_for_key(key, chunk_list)
            sample = next((c for c in chunk_list if chunk_document_key(c) == key), None)
            sample_meta = (sample or {}).get("metadata") or {}
            cls.register_document(
                document_key=key,
                display_name=info["display_name"],
                doc_type=info["doc_type"],
                file_hash=sample_meta.get("file_hash") or None,
                is_active=True,
            )
            created += 1
            logger.info("[KB] Зарегистрирован документ: %s", key)

        if created:
            logger.info("[KB] Новых документов в реестре: %d", created)
        return created

    @classmethod
    def register_uploaded_file(
        cls,
        file_path: str | Path,
        doc_type: str,
        *,
        document_key: str | None = None,
        display_name: str | None = None,
    ) -> KnowledgeDocument:
        """Регистрация нового/обновлённого файла (build.py, management command, API)."""
        path = Path(file_path)
        key = document_key or f"{doc_type}:{path.name}"
        name = display_name or path.stem.replace("_", " ")
        return cls.register_document(
            document_key=key,
            display_name=name,
            doc_type=doc_type,
            file_path=path,
            is_active=True,
        )

    @staticmethod
    def stats() -> dict:
        qs = KnowledgeDocument.objects.all()
        return {
            "total": qs.count(),
            "active": qs.filter(is_active=True).count(),
            "inactive": qs.filter(is_active=False).count(),
        }

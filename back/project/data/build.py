"""
ETL базы знаний: обогащение метаданных чанков, загрузка документов, сборка FAISS.

Метаданные в каждом чанке (metadata):
  - document_name — имя файла или название ГОСТа / продукта
  - page_number   — номер страницы (для PDF) или null
  - doc_type      — gost | passport | catalog

Использование:
  python build.py                 — обогатить chunks.json, подхватить documents/, собрать FAISS
  python build.py --enrich-only   — только обновить metadata в chunks.json
  python build.py --index-only    — только пересобрать FAISS из текущего chunks.json

PDF/DOCX/TXT кладите в:
  documents/gost/
  documents/passport/
  documents/catalog/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DATA_DIR = Path(__file__).resolve().parent
CHUNKS_PATH = DATA_DIR / "chunks.json"
INDEX_PATH = DATA_DIR / "faiss_index.bin"
DOCUMENTS_DIR = DATA_DIR / "documents"

DOC_TYPE_DIRS = {
    "gost": "gost",
    "passport": "passport",
    "catalog": "catalog",
}

GOST_NAME_RE = re.compile(
    r"ГОСТ\s+[\d\.]+(?:\s*[-–—]\s*\d+)?(?:\s*[-–—]\s*\d{4})?",
    re.IGNORECASE,
)

CATALOG_SITE_KEY = "catalog:site"

MIN_PAGE_TEXT_LEN = 50
CHUNK_TEXT_TARGET = 1200


def _normalize_gost_name(text: str) -> Optional[str]:
    match = GOST_NAME_RE.search(text.replace("_", " "))
    return match.group(0).strip() if match else None


def _document_name_from_file(path: Path, doc_type: str) -> str:
    stem = path.stem.replace("_", " ").strip()
    if doc_type == "gost":
        gost = _normalize_gost_name(stem)
        if gost:
            return gost
    return stem


def _norm_filename(value: str) -> str:
    value = (value or "").lower().replace("ё", "е")
    return value.replace("н", "h")


def _raw_filename(value: str) -> str:
    return (value or "").casefold().replace("ё", "е")


def _is_malfunctions_filename(value: str) -> bool:
    return "неисправност" in _raw_filename(value)


def _document_kind(path: Path, doc_type: str) -> str:
    name = _norm_filename(path.name)
    if doc_type == "catalog":
        return "catalog"
    if doc_type == "gost":
        return "standard"
    if name.startswith("от ") or " от " in name or name.startswith("2024-"):
        return "type_description"
    return "manual"


def _product_identity_from_file(path: Path, doc_type: str, document_name: str) -> Dict[str, str]:
    """Единая идентичность документа для поиска и цитирования."""
    if doc_type == "catalog":
        return {
            "product_title": document_name,
            "product_family": "",
            "document_kind": "catalog",
        }
    if doc_type == "gost":
        return {
            "product_title": document_name,
            "product_family": "gost",
            "document_kind": "standard",
        }

    name = _norm_filename(path.name)
    product_title = document_name
    product_family = ""

    if "ufg" in name:
        product_family = "UFG"
        if "f z" in name or "f_z" in name or "мод. f z" in name:
            product_title = "Turbo Flow UFG-F/Z"
        elif "ufg-h" in name or "ufg-н" in path.name.lower():
            product_title = "Turbo Flow UFG-H"
        else:
            product_title = "Turbo Flow UFG"
    elif "ufl" in name:
        product_family = "UFL"
        product_title = "Turbo Flow UFL"
    elif "cfm" in name or "сfм" in name or "сfm" in name:
        product_family = "CFM"
        product_title = "Turbo Flow CFM"
    elif "tfg" in name:
        product_family = "TFG"
        product_title = "Turbo Flow TFG"
    elif "gfg" in name:
        product_family = "GFG"
        product_title = "GFG-F/GFG-dP" if "dp" in name or "dр" in name else "Turbo Flow GFG"
    elif "udm" in name:
        product_family = "UDM"
        product_title = "UDM"
    elif "плотномер" in name:
        product_family = "UDM"
        product_title = "Плотномер 4.0"
    elif _is_malfunctions_filename(path.name):
        product_family = "faults"
        product_title = document_name or "Основные неисправности приборов"

    document_kind = _document_kind(path, doc_type)
    if _is_malfunctions_filename(path.name):
        document_kind = "malfunctions"

    return {
        "product_title": product_title,
        "product_family": product_family,
        "document_kind": document_kind,
    }


def _apply_document_identity(
    chunk: Dict,
    path: Path,
    doc_type: str,
    document_name: str,
    file_hash: str,
    *,
    product_title_override: str | None = None,
    product_family_override: str | None = None,
    section_label: str | None = None,
) -> Dict:
    identity = _product_identity_from_file(path, doc_type, document_name)
    if product_title_override:
        identity["product_title"] = product_title_override
    if product_family_override:
        identity["product_family"] = product_family_override
    chunk["product_title"] = identity["product_title"]
    meta = dict(chunk.get("metadata") or {})
    meta["source_file"] = path.name
    meta["file_hash"] = file_hash
    meta["knowledge_doc_key"] = f"{doc_type}:{path.name}"
    meta["product_title"] = identity["product_title"]
    meta["product_family"] = identity["product_family"]
    meta["document_kind"] = identity["document_kind"]
    if section_label:
        meta["section_title"] = section_label
    chunk["metadata"] = meta
    return chunk


def _docx_iter_blocks(document):
    """Параграфы и таблицы в порядке следования в DOCX."""
    from docx.document import Document as DocumentClass
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if not isinstance(document, DocumentClass):
        return
    for child in document.element.body:
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _docx_section_from_paragraph(text: str) -> tuple[str | None, str | None]:
    """Возвращает (product_title, section_label) из заголовка раздела."""
    t = (text or "").strip()
    low = t.casefold().replace("ё", "е")
    if not t:
        return None, None
    if "самодиагност" in low:
        return "Turbo Flow UFG", "Функции самодиагностики расходомера"
    if "ufg" in low:
        return "Turbo Flow UFG", "Неисправности и способы устранения"
    if "tfg" in low:
        return "Turbo Flow TFG", "Неисправности и способы устранения"
    if "gfg" in low:
        return "Turbo Flow GFG", "Неисправности и способы устранения"
    return None, None


def _docx_family_from_product(product_title: str) -> str:
    title = (product_title or "").upper()
    if "UFG" in title:
        return "UFG"
    if "TFG" in title:
        return "TFG"
    if "GFG" in title:
        return "GFG"
    return "faults"


def _docx_row_is_header(cells: list[str]) -> bool:
    """Заголовок таблицы — только по первым ячейкам (не по колонке «Примечания»)."""
    head = [c.strip() for c in cells[:2] if (c or "").strip()]
    if not head:
        return False
    joined = " ".join(head).casefold().replace("ё", "е")
    markers = (
        "неисправност",
        "параметр",
        "пороговое",
        "причина",
        "метод устран",
        "возможные причины",
        "методы устран",
        "сообщение предупреж",
    )
    return any(m in joined for m in markers)


def _docx_infer_product_from_table(table) -> tuple[str | None, str | None]:
    """Определяет прибор по шапке таблицы, если заголовок раздела ещё не встречался."""
    if not table.rows:
        return None, None
    header_cells = [cell.text.strip() for cell in table.rows[0].cells]
    joined = " ".join(header_cells).casefold().replace("ё", "е")
    num_cols = len(table.columns)
    if num_cols >= 4 and "неисправност" in joined:
        return "Turbo Flow UFG", "Неисправности и способы устранения"
    if num_cols >= 4 and "параметр" in joined and "порог" in joined:
        return "Turbo Flow UFG", "Функции самодиагностики расходомера"
    return None, None


def _docx_format_fault_row(
    *,
    document_name: str,
    product_title: str,
    section_label: str,
    cells: list[str],
    table_kind: str,
) -> str:
    clean = [c.strip().replace("\n", " ") for c in cells if (c or "").strip()]
    if not clean:
        return ""
    parts = [
        f"Документ: {document_name}.",
        f"Прибор: {product_title}.",
        f"Раздел: {section_label}.",
    ]
    if table_kind == "ufg_faults" and len(clean) >= 3:
        parts.extend(
            [
                f"Неисправность: {clean[0]}.",
                f"Причина: {clean[1]}.",
                f"Метод устранения: {clean[2]}.",
            ]
        )
        if len(clean) >= 4 and clean[3]:
            parts.append(f"Примечание: {clean[3]}.")
    elif table_kind == "ufg_self_diag":
        param = clean[0] if clean[0] else "—"
        threshold = clean[1] if len(clean) > 1 else "—"
        message = clean[2] if len(clean) > 2 else "—"
        notes = clean[3] if len(clean) > 3 else ""
        parts.extend(
            [
                "Тип записи: самодиагностика.",
                f"Параметр: {param}.",
                f"Пороговое значение: {threshold}.",
                f"Сообщение: {message}.",
            ]
        )
        if notes:
            parts.append(f"Примечания: {notes}.")
    elif table_kind in ("tfg_ns", "gfg_ns") and len(clean) >= 3:
        parts.extend(
            [
                f"НС (неисправность): {clean[0]}.",
                f"Возможные причины: {clean[1]}.",
                f"Методы устранения: {clean[2]}.",
            ]
        )
    else:
        parts.append(" | ".join(clean))
    return " ".join(parts)


def _docx_table_kind(product_title: str, section_label: str, num_cols: int) -> str:
    section = (section_label or "").casefold().replace("ё", "е")
    if "UFG" in (product_title or "") and "самодиагност" in section:
        return "ufg_self_diag"
    if "UFG" in (product_title or ""):
        return "ufg_faults"
    if "TFG" in (product_title or ""):
        return "tfg_ns"
    if "GFG" in (product_title or ""):
        return "gfg_ns"
    return "generic"


def chunks_from_docx(path: Path, doc_type: str) -> List[Dict]:
    try:
        from docx import Document
    except ImportError:
        print(f"[WARN] python-docx не установлен — пропуск {path.name}", file=sys.stderr)
        return []

    document_name = _document_name_from_file(path, doc_type)
    file_hash = compute_file_hash(path)
    doc = Document(str(path))
    chunks: List[Dict] = []

    current_product: str | None = None
    current_section: str | None = None
    block_idx = 0
    table_idx = 0

    for block in _docx_iter_blocks(doc):
        if hasattr(block, "text"):
            text = (block.text or "").strip()
            if not text:
                continue
            product, section = _docx_section_from_paragraph(text)
            if product:
                current_product = product
                current_section = section
            if len(text) >= MIN_PAGE_TEXT_LEN and not product:
                base_id = f"doc_{doc_type}_{path.stem}_para_{block_idx + 1}"
                chunk = _make_doc_chunk(
                    base_id,
                    text,
                    document_name,
                    doc_type,
                    page_number=None,
                    source_file=path.name,
                    file_hash=file_hash,
                )
                chunk["metadata"]["paragraph"] = block_idx + 1
                chunks.append(
                    _apply_document_identity(
                        chunk,
                        path,
                        doc_type,
                        document_name,
                        file_hash,
                        product_title_override=current_product,
                        product_family_override=_docx_family_from_product(current_product or ""),
                        section_label=current_section,
                    )
                )
            block_idx += 1
            continue

        if current_product is None:
            inferred_product, inferred_section = _docx_infer_product_from_table(block)
            if inferred_product:
                current_product = inferred_product
                current_section = inferred_section

        if current_product is None:
            table_idx += 1
            continue

        table_kind = _docx_table_kind(current_product, current_section or "", len(block.columns))
        row_num = 0
        last_param_name = ""
        for row in block.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if table_kind == "ufg_self_diag" and cells and not cells[0].strip() and last_param_name:
                cells[0] = last_param_name
            elif table_kind == "ufg_self_diag" and cells and cells[0].strip():
                last_param_name = cells[0]
            if not any(cells) or _docx_row_is_header(cells):
                continue
            content = _docx_format_fault_row(
                document_name=document_name,
                product_title=current_product,
                section_label=current_section or "",
                cells=cells,
                table_kind=table_kind,
            )
            if len(content) < MIN_PAGE_TEXT_LEN:
                continue
            row_num += 1
            base_id = f"doc_{doc_type}_{path.stem}_tbl{table_idx}_row{row_num}"
            for part in _split_long_text(content, document_name, base_id, doc_type, None):
                chunks.append(
                    _apply_document_identity(
                        part,
                        path,
                        doc_type,
                        document_name,
                        file_hash,
                        product_title_override=current_product,
                        product_family_override=_docx_family_from_product(current_product),
                        section_label=current_section,
                    )
                )
        table_idx += 1

    return chunks


def compute_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def knowledge_doc_key_for_chunk(chunk: Dict, meta: Dict) -> str:
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


def enrich_chunk_metadata(chunk: Dict) -> Dict:
    """Добавляет document_name, page_number, doc_type в metadata чанка."""
    meta = dict(chunk.get("metadata") or {})
    product_title = (chunk.get("product_title") or "").strip()
    section_title = (meta.get("section_title") or "").strip()
    source_file = (meta.get("source_file") or "").strip()

    if not meta.get("document_name"):
        if source_file:
            meta["document_name"] = _document_name_from_file(
                Path(source_file), meta.get("doc_type", "catalog")
            )
        elif section_title and product_title:
            meta["document_name"] = f"{product_title} — {section_title}"
        elif product_title:
            meta["document_name"] = product_title
        else:
            meta["document_name"] = "Каталог turbo-don.ru"

    if not meta.get("doc_type"):
        if chunk.get("product_url"):
            meta["doc_type"] = "catalog"
        elif meta.get("type") in DOC_TYPE_DIRS:
            meta["doc_type"] = meta["type"]
        else:
            meta["doc_type"] = "catalog"

    if "page_number" not in meta:
        page_raw = meta.pop("page", None)
        meta["page_number"] = page_raw if page_raw is not None else None

    meta["knowledge_doc_key"] = knowledge_doc_key_for_chunk(chunk, meta)

    if source_file:
        identity = _product_identity_from_file(
            Path(source_file), meta.get("doc_type", "catalog"), meta["document_name"]
        )
        if not product_title:
            chunk["product_title"] = identity["product_title"]
            product_title = identity["product_title"]
        meta.setdefault("product_title", product_title)
        meta.setdefault("product_family", identity["product_family"])
        meta.setdefault("document_kind", identity["document_kind"])

    chunk["metadata"] = meta
    return chunk


def _split_long_text(text: str, document_name: str, base_chunk_id: str, doc_type: str, page_number: Optional[int]) -> List[Dict]:
    """Разбивает длинный текст на части с общими метаданными."""
    if len(text) <= CHUNK_TEXT_TARGET:
        return [{
            "chunk_id": base_chunk_id,
            "product_url": "",
            "product_title": document_name if doc_type == "catalog" else "",
            "chunk_type": doc_type,
            "content": text,
            "metadata": {
                "type": doc_type,
                "document_name": document_name,
                "doc_type": doc_type,
                "page_number": page_number,
            },
        }]

    parts: List[Dict] = []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    buffer = ""
    part_idx = 0
    for para in paragraphs:
        candidate = f"{buffer}\n\n{para}".strip() if buffer else para
        if len(candidate) > CHUNK_TEXT_TARGET and buffer:
            parts.append(_make_doc_chunk(
                f"{base_chunk_id}_part_{part_idx}",
                buffer,
                document_name,
                doc_type,
                page_number,
            ))
            part_idx += 1
            buffer = para
        else:
            buffer = candidate
    if buffer:
        parts.append(_make_doc_chunk(
            f"{base_chunk_id}_part_{part_idx}",
            buffer,
            document_name,
            doc_type,
            page_number,
        ))
    return parts


def _make_doc_chunk(
    chunk_id: str,
    content: str,
    document_name: str,
    doc_type: str,
    page_number: Optional[int],
    source_file: str = "",
    file_hash: str = "",
) -> Dict:
    meta = {
        "type": doc_type,
        "document_name": document_name,
        "doc_type": doc_type,
        "page_number": page_number,
        "knowledge_doc_key": f"{doc_type}:{source_file}" if source_file else CATALOG_SITE_KEY,
    }
    if source_file:
        meta["source_file"] = source_file
    if file_hash:
        meta["file_hash"] = file_hash
    return {
        "chunk_id": chunk_id,
        "product_url": "",
        "product_title": document_name if doc_type == "catalog" else "",
        "chunk_type": doc_type,
        "content": content,
        "metadata": meta,
    }


def _pdf_pages_text_pypdf(path: Path) -> List[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    reader = PdfReader(str(path))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def _pdf_pages_text_pymupdf(path: Path) -> List[str]:
    try:
        import fitz
    except ImportError:
        return []
    doc = fitz.open(str(path))
    pages: List[str] = []
    for page in doc:
        pages.append((page.get_text("text") or "").strip())
    doc.close()
    return pages


def _pdf_pages_to_chunks(
    pages: List[str],
    path: Path,
    doc_type: str,
    document_name: str,
    file_hash: str,
    *,
    engine: str,
) -> List[Dict]:
    chunks: List[Dict] = []
    for page_idx, text in enumerate(pages):
        if len(text) < MIN_PAGE_TEXT_LEN:
            continue
        page_number = page_idx + 1
        base_id = f"doc_{doc_type}_{path.stem}_{engine}_p{page_number}"
        for part in _split_long_text(text, document_name, base_id, doc_type, page_number):
            chunks.append(
                _apply_document_identity(part, path, doc_type, document_name, file_hash)
            )
    return chunks


def chunks_from_pdf(path: Path, doc_type: str) -> List[Dict]:
    document_name = _document_name_from_file(path, doc_type)
    file_hash = compute_file_hash(path)

    pypdf_pages = _pdf_pages_text_pypdf(path)
    chunks = _pdf_pages_to_chunks(
        pypdf_pages, path, doc_type, document_name, file_hash, engine="pypdf"
    )
    if chunks:
        return chunks

    pymupdf_pages = _pdf_pages_text_pymupdf(path)
    chunks = _pdf_pages_to_chunks(
        pymupdf_pages, path, doc_type, document_name, file_hash, engine="fitz"
    )
    if chunks:
        print(f"[INFO] {path.name}: извлечено через PyMuPDF ({len(chunks)} чанков)")
        return chunks

    if not pypdf_pages and not pymupdf_pages:
        print(f"[WARN] PDF-парсеры недоступны — пропуск {path.name}", file=sys.stderr)
        return []

    # Скан/OCR: хотя бы один чанк из имени файла для retrieval по метаданным
    identity = _product_identity_from_file(path, doc_type, document_name)
    stub = (
        f"Документ: {document_name}. Файл: {path.name}. "
        f"Продукт: {identity['product_title']}. "
        f"Тип документа: {doc_type}. "
        f"Вид: {identity['document_kind']}."
    )
    base_id = f"doc_{doc_type}_{path.stem}_stub"
    chunk = _make_doc_chunk(
        base_id, stub, document_name, doc_type, page_number=1, source_file=path.name, file_hash=file_hash
    )
    chunk.setdefault("metadata", {})["is_text_stub"] = True
    print(f"[WARN] {path.name}: текст не извлечён — stub-чанк (скан/OCR)")
    return [_apply_document_identity(chunk, path, doc_type, document_name, file_hash)]


def chunks_from_txt(path: Path, doc_type: str) -> List[Dict]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) < MIN_PAGE_TEXT_LEN:
        return []

    document_name = _document_name_from_file(path, doc_type)
    file_hash = compute_file_hash(path)
    base_id = f"doc_{doc_type}_{path.stem}"
    chunks: List[Dict] = []
    for part in _split_long_text(text, document_name, base_id, doc_type, None):
        chunks.append(
            _apply_document_identity(part, path, doc_type, document_name, file_hash)
        )
    return chunks


def load_document_chunks(documents_dir: Path) -> List[Dict]:
    if not documents_dir.is_dir():
        return []

    all_chunks: List[Dict] = []
    handlers = {
        ".pdf": chunks_from_pdf,
        ".txt": chunks_from_txt,
        ".docx": chunks_from_docx,
    }

    for doc_type, subdir in DOC_TYPE_DIRS.items():
        folder = documents_dir / subdir
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            handler = handlers.get(path.suffix.lower())
            if not handler:
                print(f"[WARN] неподдерживаемый формат: {path}", file=sys.stderr)
                continue
            file_chunks = handler(path, doc_type)
            print(f"[INFO] {path.name}: {len(file_chunks)} чанков ({doc_type})")
            all_chunks.extend(file_chunks)

    return all_chunks


def enrich_all_chunks(chunks: List[Dict]) -> List[Dict]:
    return [enrich_chunk_metadata(dict(c)) for c in chunks]


def merge_chunks(catalog_chunks: List[Dict], document_chunks: List[Dict]) -> List[Dict]:
    seen_ids = {c.get("chunk_id") for c in catalog_chunks if c.get("chunk_id")}
    merged = list(catalog_chunks)
    for chunk in document_chunks:
        cid = chunk.get("chunk_id")
        if cid and cid in seen_ids:
            print(f"[WARN] дубликат chunk_id пропущен: {cid}", file=sys.stderr)
            continue
        merged.append(chunk)
        if cid:
            seen_ids.add(cid)
    return merged


def base_catalog_chunks(chunks: List[Dict]) -> List[Dict]:
    """Оставляет из существующего chunks.json только каталог сайта.

    Документные чанки каждый раз строятся заново из documents/*, иначе после
    удаления/замены PDF в индексе остаются устаревшие документы.
    """
    catalog: List[Dict] = []
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        doc_type = meta.get("doc_type") or chunk.get("chunk_type")
        if doc_type == "catalog" or chunk.get("product_url"):
            catalog.append(chunk)
    return catalog


def count_products(chunks: List[Dict]) -> int:
    urls = {c.get("product_url") for c in chunks if c.get("product_url")}
    return len(urls)


def save_chunks(chunks: List[Dict]) -> None:
    payload = {
        "total_chunks": len(chunks),
        "total_products": count_products(chunks),
        "metadata_schema_version": 1,
        "chunks": chunks,
    }
    with open(CHUNKS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[INFO] chunks.json saved: {len(chunks)} chunks -> {CHUNKS_PATH}")


def _faiss_write_path(target: Path) -> Path:
    """FAISS на Windows не пишет в пути с кириллицей — временный ASCII-файл."""
    try:
        str(target).encode("ascii")
        return target
    except UnicodeEncodeError:
        mirror = Path(r"C:\temp\chatbot\_build_mirror")
        mirror.mkdir(parents=True, exist_ok=True)
        return mirror / target.name


def build_faiss_index(chunks: List[Dict]) -> None:
    if not chunks:
        raise ValueError("Список чанков пуст — FAISS не собран")

    print(f"[INFO] Loading embedding model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)
    texts = [c["content"] for c in chunks]

    print(f"[INFO] Embeddings for {len(texts)} chunks...")
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=len(texts) > 100,
    ).astype("float32")

    dim = embeddings.shape[1]
    print(f"[INFO] Embedding dim: {dim}")

    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    write_path = _faiss_write_path(INDEX_PATH)
    faiss.write_index(index, str(write_path))
    if write_path != INDEX_PATH:
        shutil.copy2(write_path, INDEX_PATH)
        print(f"[INFO] FAISS index copied to: {INDEX_PATH}")
    print(f"[INFO] FAISS index saved: {INDEX_PATH}")


def load_existing_chunks() -> List[Dict]:
    with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("chunks.json должен содержать массив 'chunks'")
    return chunks


def run_enrich_and_build(*, enrich_only: bool = False, index_only: bool = False) -> None:
    if index_only:
        chunks = load_existing_chunks()
        build_faiss_index(chunks)
        return

    catalog_chunks = enrich_all_chunks(base_catalog_chunks(load_existing_chunks()))
    document_chunks = enrich_all_chunks(load_document_chunks(DOCUMENTS_DIR))
    all_chunks = merge_chunks(catalog_chunks, document_chunks)

    with_meta = sum(
        1 for c in all_chunks
        if (c.get("metadata") or {}).get("document_name")
        and (c.get("metadata") or {}).get("doc_type") is not None
    )
    print(f"[INFO] Чанков с document_name + doc_type: {with_meta}/{len(all_chunks)}")

    save_chunks(all_chunks)

    if enrich_only:
        print("[INFO] --enrich-only: FAISS не пересобран")
        return

    build_faiss_index(all_chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка chunks.json и FAISS-индекса")
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Только обогатить metadata в chunks.json, без FAISS",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Только пересобрать FAISS из текущего chunks.json",
    )
    args = parser.parse_args()

    if args.enrich_only and args.index_only:
        parser.error("Укажите только один из флагов: --enrich-only или --index-only")

    run_enrich_and_build(enrich_only=args.enrich_only, index_only=args.index_only)


if __name__ == "__main__":
    main()

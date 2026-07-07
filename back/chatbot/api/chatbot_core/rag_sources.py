# -*- coding: utf-8 -*-
"""Источники RAG для виджета под ответом и очистка inline-цитат из текста LLM."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

from .chunk_access import CATALOG_SITE_KEY, chunk_document_key
from .product_detector import _series_in_text

_INLINE_CITATION_RE = re.compile(r"\s*\[Документ:\s*[^\]]+\]\s*", re.IGNORECASE)
_INLINE_SOURCE_NOTE_RE = re.compile(r"\s*\(источник не указан\)\s*", re.IGNORECASE)
_MAX_PAGES_PER_FILE = 4


def strip_inline_citations(text: str) -> str:
    """Убирает повторяющиеся [Документ: …] из текста ответа."""
    if not text:
        return ""
    cleaned = _INLINE_CITATION_RE.sub(" ", text)
    cleaned = _INLINE_SOURCE_NOTE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\s*;\s*", "; ", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    return cleaned.strip()


def _source_identity(chunk: Dict[str, Any]) -> Tuple[str, str, str]:
    meta = chunk.get("metadata") or {}
    doc_key = (meta.get("knowledge_doc_key") or chunk_document_key(chunk) or "").strip()
    title = (meta.get("document_name") or chunk.get("product_title") or "").strip()
    page_raw = meta.get("page_number", meta.get("page"))
    page = str(page_raw).strip() if page_raw is not None and str(page_raw).strip() else ""
    return doc_key, title, page


def _parse_page_number(page: str) -> Optional[int]:
    if not page:
        return None
    match = re.search(r"\d+", str(page))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _format_page_list(pages: List[int]) -> str:
    if not pages:
        return ""
    unique = sorted(set(pages))
    ranges: List[Tuple[int, int]] = []
    start = unique[0]
    prev = unique[0]
    for page_num in unique[1:]:
        if page_num == prev + 1:
            prev = page_num
            continue
        ranges.append((start, prev))
        start = prev = page_num
    ranges.append((start, prev))
    parts: List[str] = []
    for begin, end in ranges:
        parts.append(str(begin) if begin == end else f"{begin}–{end}")
    return "стр. " + ", ".join(parts)


def _group_key(chunk: Dict[str, Any]) -> Tuple[str, str]:
    doc_key, title, _page = _source_identity(chunk)
    return (doc_key or title, title)


def _chunk_series_set(chunk: Dict[str, Any]) -> Set[str]:
    meta = chunk.get("metadata") or {}
    blob = " ".join(
        [
            str(chunk.get("product_title") or ""),
            str(meta.get("document_name") or ""),
            str(meta.get("source_file") or ""),
            str(chunk.get("content") or "")[:240],
        ]
    )
    return _series_in_text(blob)


def _series_from_product_name(product_name: str) -> Set[str]:
    return _series_in_text(product_name or "")


def _target_series_for_sources(
    *,
    question: str = "",
    answer: str = "",
    detected_products: Optional[List[Tuple[str, float]]] = None,
) -> Optional[Set[str]]:
    """Одна целевая серия — фильтруем источники; несколько — оставляем как есть."""
    q_series = _series_in_text(question)
    a_series = _series_in_text(answer)
    if len(q_series) == 1:
        return q_series
    if len(a_series) == 1:
        return a_series
    if len(q_series) >= 2 or len(a_series) >= 2:
        return None
    if detected_products and len(detected_products) == 1:
        product_series = _series_from_product_name(detected_products[0][0])
        if len(product_series) == 1:
            return product_series
    return None


def filter_source_chunks(
    chunks: List[Dict[str, Any]],
    *,
    question: str = "",
    answer: str = "",
    detected_products: Optional[List[Tuple[str, float]]] = None,
) -> List[Dict[str, Any]]:
    """Оставляет чанки только по серии, явно указанной в вопросе/ответе."""
    target = _target_series_for_sources(
        question=question,
        answer=answer,
        detected_products=detected_products,
    )
    if not target:
        return list(chunks or [])

    marker = next(iter(target))
    filtered = [c for c in (chunks or []) if marker in _chunk_series_set(c)]
    return filtered if filtered else list(chunks or [])


def _resolve_document_href(chunk: Dict[str, Any]) -> str:
    meta = chunk.get("metadata") or {}
    for raw in (meta.get("url"), chunk.get("product_url"), meta.get("doc_url")):
        href = (raw or "").strip()
        if href.startswith("http://") or href.startswith("https://"):
            return href

    doc_key = (meta.get("knowledge_doc_key") or chunk_document_key(chunk) or "").strip()
    if doc_key and doc_key != CATALOG_SITE_KEY:
        return f"knowledge-doc/download/?key={quote(doc_key, safe='')}"
    return ""


def _action_label(title: str) -> str:
    return f"Открыть «{title}»"


def _top_pages_by_score(page_scores: Dict[int, float], *, limit: int) -> List[int]:
    if not page_scores:
        return []
    ordered = sorted(page_scores.items(), key=lambda item: (-item[1], item[0]))
    return [page for page, _score in ordered[:limit]]


def build_rag_sources(chunks: List[Dict[str, Any]], *, max_sources: int = 4) -> List[Dict[str, Any]]:
    """
    Уникальные источники для виджета под RAG-ответом — один виджет на файл.
    Страницы из нескольких чанков объединяются в description (топ по score).
    """
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for chunk in chunks or []:
        key = _group_key(chunk)
        doc_key, title, page_str = _source_identity(chunk)
        if not title:
            continue

        score = float(chunk.get("score") or 0)
        page_num = _parse_page_number(page_str)
        product = (chunk.get("product_title") or "").strip()
        href = _resolve_document_href(chunk)

        if key not in groups:
            groups[key] = {
                "doc_key": doc_key,
                "title": title,
                "product": product,
                "score": score,
                "page_scores": {},
                "href": href,
            }
        else:
            entry = groups[key]
            entry["score"] = max(entry["score"], score)
            if not entry["product"] and product:
                entry["product"] = product
            if not entry["href"] and href:
                entry["href"] = href

        if page_num is not None:
            prev = groups[key]["page_scores"].get(page_num, 0.0)
            groups[key]["page_scores"][page_num] = max(prev, score)

    ranked = sorted(groups.values(), key=lambda g: g["score"], reverse=True)
    out: List[Dict[str, Any]] = []

    for entry in ranked[:max_sources]:
        title = entry["title"]
        product = entry["product"]
        pages = _top_pages_by_score(entry["page_scores"], limit=_MAX_PAGES_PER_FILE)
        pages_text = _format_page_list(pages)

        subtitle_parts: List[str] = []
        if product and product.casefold() not in title.casefold():
            subtitle_parts.append(product)
        if pages_text:
            subtitle_parts.append(pages_text)

        href = entry["href"]
        actions: List[Dict[str, str]] = []
        if href:
            action_type = "file" if "knowledge-doc/" in href or href.lower().endswith(".pdf") else "url"
            actions.append(
                {
                    "type": action_type,
                    "label": _action_label(title),
                    "href": href,
                    "value": title,
                }
            )

        out.append(
            {
                "id": entry["doc_key"] or title,
                "title": title,
                "description": " · ".join(subtitle_parts),
                "page": pages[0] if len(pages) == 1 else None,
                "pages": pages,
                "doc_key": entry["doc_key"] or None,
                "actions": actions,
            }
        )

    return out

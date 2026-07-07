# -*- coding: utf-8 -*-
"""Переписывание пользовательского вопроса перед RAG-поиском."""

from __future__ import annotations

import re

_MEDIUM_WORD_RE = re.compile(r"\bсред[аыуеой]{0,3}\b", re.IGNORECASE)
_SOFTWARE_CONTEXT_RE = re.compile(
    r"программн|оболочк|\bпо\b|firmware|software|интерфейс\s*пользовател",
    re.IGNORECASE,
)
_SERIES_HINT_RE = re.compile(r"\b(ufg|tfg|ufl|cfm|gfg|udm|cng)\b", re.IGNORECASE)


def rewrite_rag_question(question: str) -> str:
    """
    Уточняет неоднозначные формулировки для retrieval и LLM.
    Исходный смысл сохраняется, добавляется явный контекст.
    """
    text = (question or "").strip()
    if not text:
        return text

    ql = text.casefold().replace("ё", "е")
    if _MEDIUM_WORD_RE.search(ql) and not _SOFTWARE_CONTEXT_RE.search(ql):
        if (
            _SERIES_HINT_RE.search(ql)
            or "какая среда" in ql
            or "какие среды" in ql
            or "для какой среды" in ql
            or "для каких сред" in ql
        ):
            return (
                f"{text}. "
                "Имеется в виду измеряемая среда (газ или жидкость), "
                "для какой среды предназначен прибор, а не программная среда."
            )
    return text

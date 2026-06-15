"""Гибридный поиск: BM25 + векторное сходство (FAISS)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import numpy as np
from rank_bm25 import BM25Okapi

from .chunk_access import is_chunk_searchable


def _tokenize(text: str) -> List[str]:
    """Простая токенизация для русского/латиницы и цифр (без nltk)."""
    text = (text or "").lower()
    return [t for t in re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", text) if len(t) > 1]


class HybridRetriever:
    """BM25 по content чанков + vector score из VectorStore."""

    def __init__(self, vector_store, vector_weight: float = 0.5):
        self.store = vector_store
        self.chunks = vector_store.chunks
        self.vector_weight = vector_weight
        self.corpus_tokens = [
            _tokenize(
                " ".join(
                    (
                        c.get("content", ""),
                        (c.get("metadata") or {}).get("source_file", ""),
                        (c.get("metadata") or {}).get("document_name", ""),
                        c.get("product_title", ""),
                    )
                )
            )
            for c in self.chunks
        ]
        self.bm25 = BM25Okapi(self.corpus_tokens)
        self._chunk_id_to_idx: Dict[str, int] = {
            c["chunk_id"]: i
            for i, c in enumerate(self.chunks)
            if c.get("chunk_id")
        }

    @staticmethod
    def _minmax_norm(scores: Dict[str, float]) -> Dict[str, float]:
        if not scores:
            return {}
        lo = min(scores.values())
        hi = max(scores.values())
        if hi <= lo:
            return {k: (1.0 if v > 0 else 0.0) for k, v in scores.items()}
        return {k: (v - lo) / (hi - lo) for k, v in scores.items()}

    def _chunk_result(self, idx: int, score: float) -> Dict:
        chunk = self.chunks[idx]
        return {
            "chunk_id": chunk.get("chunk_id"),
            "chunk_type": chunk.get("chunk_type"),
            "product_title": chunk.get("product_title"),
            "content": chunk.get("content"),
            "metadata": chunk.get("metadata", {}),
            "score": score,
        }

    def search(
        self,
        query: str,
        query_embedding: np.ndarray,
        top_k: int,
        product_filter: Optional[str] = None,
    ) -> List[Dict]:
        fetch_k = min(len(self.chunks), max(top_k * 3, top_k))
        vector_results = self.store.search(query_embedding, fetch_k, product_filter)
        vector_by_id = {
            r["chunk_id"]: float(r.get("score", 0.0))
            for r in vector_results
            if r.get("chunk_id")
        }

        query_tokens = _tokenize(query)
        if not query_tokens:
            return vector_results[:top_k]

        bm25_all = self.bm25.get_scores(query_tokens)

        candidate_indices = set()
        for cid in vector_by_id:
            if cid in self._chunk_id_to_idx:
                candidate_indices.add(self._chunk_id_to_idx[cid])

        bm25_top = np.argsort(bm25_all)[::-1][:fetch_k]
        for idx in bm25_top:
            candidate_indices.add(int(idx))

        raw_bm25: Dict[str, float] = {}
        raw_vector: Dict[str, float] = {}
        for idx in candidate_indices:
            chunk = self.chunks[idx]
            if not is_chunk_searchable(chunk, self.store.active_doc_keys):
                continue
            cid = chunk.get("chunk_id")
            if not cid:
                continue
            if product_filter:
                title = (chunk.get("product_title") or "").lower()
                if product_filter.lower() not in title:
                    continue
            raw_bm25[cid] = float(bm25_all[idx])
            raw_vector[cid] = vector_by_id.get(cid, 0.0)

        norm_bm25 = self._minmax_norm(raw_bm25)
        positive_vector = {k: v for k, v in raw_vector.items() if v > 0}
        norm_vector = self._minmax_norm(positive_vector)

        vw = self.vector_weight
        bw = 1.0 - vw

        merged: List[Dict] = []
        for cid, b_raw in raw_bm25.items():
            idx = self._chunk_id_to_idx[cid]
            b_norm = norm_bm25.get(cid, 0.0)
            v_norm = norm_vector.get(cid, 0.0)
            combined = bw * b_norm + vw * v_norm
            merged.append(self._chunk_result(idx, combined))

        merged.sort(key=lambda x: x["score"], reverse=True)
        return merged[:top_k]

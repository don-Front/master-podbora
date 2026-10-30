"""Optional cross-encoder reranker for final RAG context selection."""

from __future__ import annotations

import logging
import time
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


class OptionalCrossEncoderReranker:
    """Lazy cross-encoder reranker with safe fallback to current chunk order."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        candidates: int = 40,
        timeout_ms: int = 2500,
    ) -> None:
        self.enabled = bool(enabled)
        self.model_name = model_name
        self.candidates = max(1, int(candidates or 40))
        self.timeout_ms = max(100, int(timeout_ms or 2500))
        self._model = None
        self._disabled_reason = ""

    @property
    def available(self) -> bool:
        return self.enabled and not self._disabled_reason

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not self.available:
            return None
        try:
            from sentence_transformers import CrossEncoder

            started = time.perf_counter()
            self._model = CrossEncoder(self.model_name)
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "RAG reranker loaded: model=%s elapsed_ms=%.0f",
                self.model_name,
                elapsed_ms,
            )
            return self._model
        except Exception as exc:
            self._disabled_reason = str(exc)
            logger.exception("RAG reranker disabled: failed to load %s", self.model_name)
            return None

    @staticmethod
    def _chunk_text(chunk: Dict) -> str:
        meta = chunk.get("metadata") or {}
        parts = (
            chunk.get("product_title"),
            chunk.get("chunk_type"),
            meta.get("document_name"),
            meta.get("source_file"),
            meta.get("section_title"),
            meta.get("paragraph"),
            chunk.get("content"),
        )
        return "\n".join(str(part) for part in parts if part)

    @staticmethod
    def _normalize(scores: np.ndarray) -> np.ndarray:
        if scores.size == 0:
            return scores
        lo = float(scores.min())
        hi = float(scores.max())
        if hi <= lo:
            return np.ones_like(scores, dtype=float)
        return (scores - lo) / (hi - lo)

    def rerank(self, query: str, chunks: List[Dict], *, top_k: int) -> List[Dict]:
        """Rerank candidate chunks; return original order if reranker is unavailable."""
        if not self.available or not chunks:
            return chunks[:top_k]

        model = self._load_model()
        if model is None:
            return chunks[:top_k]

        candidates = chunks[: self.candidates]
        pairs = [(query, self._chunk_text(chunk)) for chunk in candidates]

        started = time.perf_counter()
        try:
            raw_scores = model.predict(pairs, show_progress_bar=False)
            elapsed_ms = (time.perf_counter() - started) * 1000
            if elapsed_ms > self.timeout_ms:
                logger.warning(
                    "RAG reranker slow: elapsed_ms=%.0f timeout_ms=%s model=%s",
                    elapsed_ms,
                    self.timeout_ms,
                    self.model_name,
                )

            scores = np.asarray(raw_scores, dtype=float).reshape(-1)
            normalized = self._normalize(scores)
            ranked: List[Dict] = []
            for chunk, rerank_score in zip(candidates, normalized):
                item = dict(chunk)
                original = float(item.get("score") or 0.0)
                item["rerank_score"] = float(rerank_score)
                item["score"] = original + float(rerank_score) * 2.0
                ranked.append(item)

            ranked.sort(key=lambda item: item.get("score", 0.0), reverse=True)
            return ranked[:top_k]
        except Exception as exc:
            self._disabled_reason = str(exc)
            logger.exception("RAG reranker disabled: predict failed")
            return chunks[:top_k]

import faiss
import json
import numpy as np
from typing import List, Dict, Optional, Set

from .chunk_access import is_chunk_searchable


class VectorStore:
    def __init__(
        self,
        index_path: str,
        chunks_path: str,
        active_doc_keys: Optional[Set[str]] = None,
    ):
        self.index = faiss.read_index(index_path)

        with open(chunks_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.chunks = data["chunks"]

        if not isinstance(self.chunks, list):
            raise ValueError("chunks.json должен содержать массив 'chunks'")

        self.active_doc_keys = active_doc_keys

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int,
        product_filter: Optional[str] = None
    ) -> List[Dict]:
        # Проверяем размерность вектора
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        elif query_embedding.ndim != 2:
            raise ValueError(f"query_embedding должен быть 1D или 2D, получено {query_embedding.shape}")

        similarities, indices = self.index.search(query_embedding, top_k)

        results = []
        query_lower = product_filter.lower() if product_filter else None

        for similarity, idx in zip(similarities[0], indices[0]):
            if idx == -1:
                continue
            chunk = self.chunks[idx]

            if not is_chunk_searchable(chunk, self.active_doc_keys):
                continue

            # фильтр по названию продукта
            if query_lower and query_lower not in chunk["product_title"].lower():
                continue

            score = float(similarity)
            results.append({
                "chunk_id": chunk.get("chunk_id"),
                "chunk_type": chunk.get("chunk_type"),
                "product_title": chunk.get("product_title"),
                "content": chunk.get("content"),
                "metadata": chunk.get("metadata", {}),
                "score": score
            })

        return results


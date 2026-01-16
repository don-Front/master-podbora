import faiss
import json
import numpy as np
from typing import List, Dict, Optional

class VectorStore:
    def __init__(self, index_path: str, chunks_path: str):
        self.index = faiss.read_index(index_path)

        with open(chunks_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.chunks = data["chunks"]

        if not isinstance(self.chunks, list):
            raise ValueError("chunks.json должен содержать массив 'chunks'")

    def search(
    self,
    query_embedding: np.ndarray,
    top_k: int,
    product_filter: Optional[str] = None
    ) -> List[Dict]:
        # Проверяем размерность вектора
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)  # shape = (1, dim)
        elif query_embedding.ndim != 2:
            raise ValueError(f"query_embedding должен быть 1D или 2D, получено {query_embedding.shape}")

        distances, indices = self.index.search(query_embedding, top_k)

        results = []
        query_lower = product_filter.lower() if product_filter else None

        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            chunk = self.chunks[idx]

            # фильтр по названию продукта
            if query_lower and query_lower not in chunk["product_title"].lower():
                continue

            confidence = 1 - float(dist) / 2
            results.append({
                "chunk_id": chunk.get("chunk_id"),
                "chunk_type": chunk.get("chunk_type"),
                "product_title": chunk.get("product_title"),
                "content": chunk.get("content"),
                "metadata": chunk.get("metadata", {}),
                "score": confidence
            })

        return results


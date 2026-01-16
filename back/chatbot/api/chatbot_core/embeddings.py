from sentence_transformers import SentenceTransformer
import numpy as np


class EmbeddingModel:
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def encode(self, text: str):
        """Кодирует один текст"""
        if isinstance(text, str):
            text = [text]
        embeddings = self.model.encode(text, normalize_embeddings=True)
        return embeddings[0] if len(embeddings) == 1 else embeddings
    
    def encode_batch(self, texts: list):
        """Кодирует несколько текстов за раз"""
        if not texts:
            return np.array([])
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings


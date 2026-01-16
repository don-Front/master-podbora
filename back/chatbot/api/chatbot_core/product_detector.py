import numpy as np
import re
from typing import Dict, List, Optional, Tuple


class ProductDetector:
    def __init__(self, store, embedder):
        self.store = store
        self.embedder = embedder
        self.product_embeddings = {}
        self.all_products = None
        
    def extract_product_names(self) -> List[str]:
        """Извлекает все уникальные названия продуктов из векторного хранилища"""
        if self.all_products is not None:
            return self.all_products
            
        product_names = set()
        for chunk in self.store.chunks:
            if "product_title" in chunk:
                title = chunk["product_title"]
                # Убираем лишние детали в скобках
                title = re.sub(r'\(.*?\)', '', title)
                # Берем только основную часть (первые 5-7 слов)
                words = title.split()
                if len(words) > 7:
                    title = ' '.join(words[:7])
                title = title.strip()
                if title and len(title) > 3:
                    product_names.add(title)
        
        self.all_products = sorted(list(product_names))
        return self.all_products
    
    def detect_product_from_question(self, question: str) -> Tuple[Optional[str], float]:
        """Определяет продукт из вопроса с помощью эмбеддингов"""
        try:
            products = self.extract_product_names()
            
            if not products:
                return None, 0.0
            
            question_embedding = self.embedder.encode(question)
            
            # Кодируем названия продуктов с кэшированием
            for product in products:
                if product not in self.product_embeddings:
                    self.product_embeddings[product] = self.embedder.encode(product)
            
            best_product = None
            best_score = 0.0
            
            for product, product_emb in self.product_embeddings.items():
                question_norm = question_embedding / np.linalg.norm(question_embedding)
                product_norm = product_emb / np.linalg.norm(product_emb)
                similarity = np.dot(question_norm, product_norm)
                
                if similarity > best_score:
                    best_score = similarity
                    best_product = product
            
            threshold = 0.4
            
            if best_score > threshold:
                return best_product, best_score
            else:
                return None, best_score
                
        except Exception as e:
            print(f"[ERROR] Ошибка при определении продукта: {e}")
            return None, 0.0
    
    def search_chunks_by_product(self, product_name: str, top_k: int = 10) -> List[Dict]:
        """Ищет чанки по названию продукта"""
        results = []
        product_lower = product_name.lower()
        
        product_variations = [
            product_lower,
            product_lower.replace("-", " "),
            product_lower.replace(" ", "-")
        ]
        
        for chunk in self.store.chunks:
            chunk_product = chunk.get("product_title", "").lower()
            
            match_found = False
            for variant in product_variations:
                if variant and (variant in chunk_product or chunk_product in variant):
                    match_found = True
                    break
            
            if match_found:
                content = chunk.get("content", "").lower()
                score = 0.8
                
                if product_lower in chunk_product:
                    score = 0.9
                
                results.append({
                    "chunk_id": chunk.get("chunk_id"),
                    "chunk_type": chunk.get("chunk_type"),
                    "product_title": chunk.get("product_title"),
                    "content": chunk.get("content"),
                    "metadata": chunk.get("metadata", {}),
                    "score": score
                })
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


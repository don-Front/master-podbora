import numpy as np
import re
from typing import Dict, List, Optional, Set, Tuple

from .chunk_access import is_chunk_searchable


_TOKEN_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]+")
_STOP_WORDS = {
    "для",
    "или",
    "что",
    "как",
    "какие",
    "какой",
    "какая",
    "какое",
    "при",
    "это",
    "его",
    "она",
    "они",
    "the",
    "and",
    "with",
    "flow",
    "turbo",
}


def _tokenize(text: str) -> Set[str]:
    """Быстрая токенизация для ранжирования продуктовых чанков без embedding."""
    return {
        token
        for token in _TOKEN_RE.findall((text or "").lower())
        if len(token) > 2 and token not in _STOP_WORDS
    }


def _normalize_for_match(text: str) -> str:
    """Нормализация для точного поиска моделей с латинскими/кириллическими символами."""
    replacements = {
        "а": "a",
        "в": "b",
        "е": "e",
        "к": "k",
        "м": "m",
        "н": "h",
        "о": "o",
        "р": "p",
        "с": "c",
        "т": "t",
        "у": "y",
        "х": "x",
    }
    value = (text or "").lower().replace("ё", "е")
    value = "".join(replacements.get(ch, ch) for ch in value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return f" {value.strip()} "


def _model_tokens(text: str) -> Set[str]:
    """Выделяет короткие модельные обозначения: ufg h, ufg f, cfm, tfg и т.п."""
    normalized = _normalize_for_match(text)
    tokens = set(re.findall(r"\b(?:ufg|ufl|cfm|tfg|gfg|udm|cng|flg|ulg|dp|[fhz])\b", normalized))
    compact = normalized.replace(" ", "")
    for model in ("ufgh", "ufgf", "ufgz", "gfgdp", "cng", "flg", "ulg"):
        if model in compact:
            tokens.add(model)
    return tokens


_SERIES_MARKERS = ("ufg", "tfg", "ufl", "cfm", "gfg", "udm", "cng")


def _series_in_text(text: str) -> Set[str]:
    """Серии Turbo Flow, явно упомянутые в вопросе (UFG, TFG и т.д.)."""
    compact = _normalize_for_match(text).replace(" ", "")
    return {marker for marker in _SERIES_MARKERS if marker in compact}


def _best_product_for_series(series: str, products: List[str]) -> Tuple[Optional[str], float]:
    """Лучшее название продукта из каталога для серии (ufg, tfg…)."""
    best_product: Optional[str] = None
    best_score = 0.0
    for product in products:
        normalized = _normalize_for_match(product).replace(" ", "")
        if series not in normalized:
            continue
        score = 0.72
        pl = product.lower()
        if "turbo flow" in pl:
            score += 0.12
        if series in _model_tokens(product):
            score += 0.1
        if "расходомер" in pl or "счетчик" in pl or "счётчик" in pl:
            score += 0.05
        if score > best_score:
            best_score = score
            best_product = product
    return best_product, best_score


def _chunk_product_text(chunk: Dict) -> str:
    meta = chunk.get("metadata") or {}
    return " ".join(
        str(v or "")
        for v in (
            chunk.get("product_title"),
            meta.get("product_title"),
            meta.get("product_family"),
            meta.get("document_name"),
            meta.get("source_file"),
        )
    )


def _keyword_product_candidate(question: str, products: List[str]) -> Tuple[Optional[str], float]:
    """Подсказка для общих запросов по среде, где модель явно не названа."""
    q = (question or "").casefold().replace("ё", "е")
    if not (
        "расходомер" in q
        and any(marker in q for marker in ("нефт", "жидк", "масл", "нефтепродукт"))
    ):
        return None, 0.0

    normalized_products = [(product, _normalize_for_match(product)) for product in products]
    priorities = ("cfm ulg", "turbo flow cfm", "cfm", "turbo flow ufl", "ufl")
    for marker in priorities:
        marker_norm = f" {_normalize_for_match(marker).strip()} "
        for product, normalized in normalized_products:
            if marker_norm in normalized:
                return product, 0.78
    return None, 0.0


def _is_malfunction_chunk(meta: dict) -> bool:
    if (meta or {}).get("document_kind") == "malfunctions":
        return True
    source = ((meta or {}).get("source_file") or "").casefold().replace("ё", "е")
    return "неисправност" in source


def _is_malfunction_query(text: str) -> bool:
    q = (text or "").casefold().replace("ё", "е")
    markers = (
        "неисправ",
        "устран",
        "самодиагност",
        "авар",
        "ненорма",
        "внимание",
        " нс ",
        "причин",
        "метод устран",
        "методы устран",
        "неисправност",
        "сигнал-шум",
        "соотношение сигнал",
        "арu",
        "завихрен",
        "симметри",
        "не работает",
        "не включа",
        "не показыва",
        "оборвал",
        " сломал",
        "перестал",
        "не горит",
        "нет индикац",
        "не видно",
        "ошибк",
    )
    return any(m in q for m in markers)


def _explicit_equipment_in_question(question: str) -> bool:
    """True, если пользователь явно назвал серию или модель прибора."""
    if _series_in_text(question):
        return True
    compact = _normalize_for_match(question).replace(" ", "")
    return any(marker in compact for marker in _SERIES_MARKERS)


TROUBLESHOOTING_EQUIPMENT_CLARIFY = (
    "Чтобы подсказать неисправность и способ устранения, уточните, пожалуйста, "
    "модель или серию прибора — например, Turbo Flow UFG, TFG, UFL, CFM."
)


def needs_troubleshooting_equipment_clarification(
    question: str,
    detected_products: Optional[List[Tuple[str, float]]] = None,
) -> bool:
    """
    Запрос про неисправность/симптом без явного указания оборудования —
    нужно уточнение, а не RAG по случайной серии.

    Embedding-детектор продукта игнорируется: он часто «угадывает» UFG
    по общим словам (индикатор, провод) и даёт ложный ответ.
    """
    del detected_products  # не используем — только явный текст вопроса
    if not _is_malfunction_query(question):
        return False
    return not _explicit_equipment_in_question(question)


def looks_like_equipment_clarification_reply(text: str) -> bool:
    """Короткий ответ только с моделью/серией после запроса уточнения."""
    t = (text or "").strip()
    if not t or len(t) > 64:
        return False
    if not _explicit_equipment_in_question(t):
        return False
    if _is_malfunction_query(t):
        return False
    return True


def merge_troubleshooting_followup(original_question: str, equipment_reply: str) -> str:
    """Склеивает исходный симптом и уточнённую модель в один RAG-запрос."""
    base = (original_question or "").strip()
    equipment = (equipment_reply or "").strip()
    if not base:
        return equipment
    if not equipment:
        return base
    return f"{base}. Прибор/серия: {equipment}"


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
        active_keys = getattr(self.store, "active_doc_keys", None)
        for chunk in self.store.chunks:
            if not is_chunk_searchable(chunk, active_keys):
                continue
            meta = chunk.get("metadata") or {}
            for raw_title in (
                chunk.get("product_title"),
                meta.get("product_title"),
                meta.get("product_family"),
            ):
                title = (raw_title or "").strip()
                if not title:
                    continue
                # Убираем лишние детали в скобках
                title = re.sub(r'\(.*?\)', '', title)
                # Берем только основную часть (первые 5-7 слов)
                words = title.split()
                if len(words) > 7:
                    title = ' '.join(words[:7])
                title = title.strip()
                if title and len(title) > 2:
                    product_names.add(title)
        
        self.all_products = sorted(list(product_names))
        return self.all_products
    
    def detect_product_from_question(
        self,
        question: str,
        query_embedding: Optional[np.ndarray] = None,
    ) -> Tuple[Optional[str], float]:
        """Определяет продукт из вопроса с помощью эмбеддингов"""
        try:
            products = self.extract_product_names()
            
            if not products:
                return None, 0.0

            question_tokens = _model_tokens(question)
            if question_tokens:
                best_exact = None
                best_exact_score = 0
                for product in products:
                    product_tokens = _model_tokens(product)
                    score = len(question_tokens & product_tokens)
                    if score > best_exact_score:
                        best_exact = product
                        best_exact_score = score
                if best_exact and best_exact_score >= 1:
                    return best_exact, 0.95

            keyword_product, keyword_score = _keyword_product_candidate(question, products)
            if keyword_product:
                return keyword_product, keyword_score
            
            question_embedding = (
                query_embedding if query_embedding is not None else self.embedder.encode(question)
            )
            
            # Кодируем названия продуктов батчем и кэшируем, чтобы не делать
            # десятки отдельных forward pass на первом вопросе после рестарта.
            missing_products = [p for p in products if p not in self.product_embeddings]
            if missing_products:
                if hasattr(self.embedder, "encode_batch"):
                    embeddings = self.embedder.encode_batch(missing_products)
                else:
                    embeddings = [self.embedder.encode(product) for product in missing_products]
                for product, product_emb in zip(missing_products, embeddings):
                    self.product_embeddings[product] = product_emb
            
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

    def detect_products_from_question(
        self,
        question: str,
        query_embedding: Optional[np.ndarray] = None,
    ) -> List[Tuple[str, float]]:
        """
        Определяет один или несколько продуктов из вопроса.
        Если в тексте явно несколько серий (UFG и TFG) — возвращает обе.
        """
        series = _series_in_text(question)
        if len(series) >= 2:
            products = self.extract_product_names()
            matched: List[Tuple[str, float]] = []
            for marker in sorted(series):
                product, score = _best_product_for_series(marker, products)
                if product and score >= 0.5:
                    matched.append((product, score))
            if len(matched) >= 2:
                return matched[:4]

        single = self.detect_product_from_question(question, query_embedding=query_embedding)
        if single[0]:
            return [single]
        return []

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a / na, b / nb))

    def search_chunks_by_product(
        self,
        product_name: str,
        top_k: int = 10,
        query_embedding: Optional[np.ndarray] = None,
        query_text: str = "",
    ) -> List[Dict]:
        """Ищет чанки по названию продукта без runtime-кодирования content."""
        results = []
        product_lower = product_name.lower()
        query_tokens = _tokenize(f"{product_name} {query_text}")
        product_model_tokens = _model_tokens(product_name)

        product_variations = [
            product_lower,
            product_lower.replace("-", " "),
            product_lower.replace(" ", "-"),
        ]

        for chunk in self.store.chunks:
            if not is_chunk_searchable(chunk, getattr(self.store, "active_doc_keys", None)):
                continue
            chunk_product_text = _chunk_product_text(chunk)
            chunk_product = chunk_product_text.lower()
            chunk_model_tokens = _model_tokens(chunk_product_text)

            match_found = False
            for variant in product_variations:
                if variant and (variant in chunk_product or chunk_product in variant):
                    match_found = True
                    break
            if not match_found and product_model_tokens and chunk_model_tokens:
                match_found = bool(product_model_tokens & chunk_model_tokens)

            if not match_found:
                continue

            # Важно: не вызываем embedder.encode(content) в цикле по чанкам.
            # Нейросетевый rerank здесь заменён дешёвым лексическим score, а
            # основной семантический сигнал всё равно приходит из FAISS/hybrid.
            content_tokens = _tokenize(chunk.get("content", ""))
            overlap = (
                len(query_tokens & content_tokens) / max(len(query_tokens), 1)
                if query_tokens
                else 0.0
            )
            score = min(0.75, 0.15 + overlap * 0.6)
            meta = chunk.get("metadata") or {}
            if meta.get("doc_type") == "passport":
                score = min(0.95, score + 0.2)
            if _is_malfunction_query(query_text):
                if _is_malfunction_chunk(meta):
                    score = min(0.98, score + 0.5)
                elif meta.get("document_kind") == "manual":
                    score = max(0.05, score - 0.12)

            results.append({
                "chunk_id": chunk.get("chunk_id"),
                "chunk_type": chunk.get("chunk_type"),
                "product_title": chunk.get("product_title"),
                "content": chunk.get("content"),
                "metadata": chunk.get("metadata", {}),
                "score": score,
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        if _is_malfunction_query(query_text):
            malfunctions = [
                r
                for r in results
                if _is_malfunction_chunk(r.get("metadata") or {})
            ]
            if malfunctions:
                rest = [r for r in results if r not in malfunctions]
                results = malfunctions + rest
        return results[:top_k]


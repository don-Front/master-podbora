import json
import os
import re
import shutil
import sys
import yaml
from typing import List, Dict, Tuple

from .embeddings import EmbeddingModel
from .vector_store import VectorStore
from .llm_client import LLMClient
from .product_detector import ProductDetector
from .question_classifier import QuestionClassifier
from .hybrid_search import HybridRetriever


def _safe_print(*args, **kwargs) -> None:
    """Print без UnicodeEncodeError в консоли Windows (cp1251)."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        end = kwargs.get("end", "\n")
        stream = kwargs.get("file", sys.stdout)
        enc = getattr(stream, "encoding", None) or "utf-8"
        stream.buffer.write(text.encode(enc, errors="replace"))
        stream.buffer.write(end.encode(enc, errors="replace"))
        stream.flush()


def adjust_search_parameters(question_type: dict, top_k: int, threshold: float) -> dict:
    """Настраивает параметры поиска"""
    
    if question_type["is_attribute"]:
        return {
            "top_k": 25,
            "context_top_k": 8,
            "threshold": 0.0,
            "chunk_types_filter": ["specifications", "basic_info", "applications", "passport", "gost"],
            "search_strategy": "aggressive"
        }
    elif question_type["is_description"]:
        return {
            "top_k": 15,
            "context_top_k": 8,
            "threshold": 0.4,
            "chunk_types_filter": ["basic_info", "applications", "passport", "gost"],
            "search_strategy": "normal"
        }
    elif question_type["is_comparison"]:
        return {
            "top_k": 20,
            "context_top_k": 10,
            "threshold": 0.3,
            "chunk_types_filter": ["specifications", "basic_info", "passport", "gost"],
            "search_strategy": "normal"
        }
    else:
        return {
            "top_k": max(top_k, 5),
            "context_top_k": max(top_k, 5),
            "threshold": threshold,
            "chunk_types_filter": None,
            "search_strategy": "normal"
        }


def _resolve_under_config_dir(config_dir: str, path_value: str) -> str:
    """Путь из yaml: абсолютный как есть, иначе относительно каталога с config.yaml."""
    if not path_value:
        return path_value
    p = path_value.strip()
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(config_dir, p))


def _faiss_readable_paths(index_path: str, chunks_path: str) -> Tuple[str, str]:
    """
    FAISS (C++) на Windows часто не открывает файлы по пути с кириллицей/Unicode.
    В таком случае копируем в C:\\temp\\chatbot\\_rag_mirror (только ASCII).
    """
    try:
        index_path.encode("ascii")
        chunks_path.encode("ascii")
        return index_path, chunks_path
    except UnicodeEncodeError:
        pass

    mirror = os.path.join(r"C:\temp\chatbot", "_rag_mirror")
    os.makedirs(mirror, exist_ok=True)
    dst_index = os.path.join(mirror, "faiss_index.bin")
    dst_chunks = os.path.join(mirror, "chunks.json")

    def copy_if_newer(src: str, dst: str) -> None:
        if not os.path.isfile(src):
            raise FileNotFoundError(src)
        if not os.path.isfile(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
            shutil.copy2(src, dst)

    copy_if_newer(index_path, dst_index)
    copy_if_newer(chunks_path, dst_chunks)
    _safe_print(f"[INFO] FAISS/chunks: копия в ASCII-путь для Windows: {mirror}")
    return dst_index, dst_chunks


def _retrieval_search(
    store,
    hybrid_retriever,
    query_embedding,
    question: str,
    top_k: int,
    *,
    use_hybrid: bool = True,
    product_filter=None,
) -> List[Dict]:
    """Векторный или гибридный (BM25 + FAISS) поиск."""
    if use_hybrid and hybrid_retriever is not None:
        return hybrid_retriever.search(question, query_embedding, top_k, product_filter)
    return store.search(query_embedding, top_k, product_filter)


_DOCUMENT_REFERENCE_RE = re.compile(
    r"(?i)\b(?:ГОСТ|СТО|РЭ|ОТ)\b|"
    r"(?:описани[ея]\s+типа)|(?:руководств[оае]\s+по\s+эксплуатации)|"
    r"(?:\b8\.\d{3}\b)|(?:\b2939\s*[-–—]?\s*63\b)|"
    r"(?:\b\d{5}[-–—]\d{2}\b)"
)


def _has_document_reference(question: str) -> bool:
    """Явная ссылка на норматив/документ: не даем ProductDetector увести поиск в каталог."""
    return bool(_DOCUMENT_REFERENCE_RE.search(question or ""))


def _chunk_doc_type(chunk: Dict) -> str:
    meta = chunk.get("metadata") or {}
    return str(meta.get("doc_type") or chunk.get("chunk_type") or "").lower()


def _document_boost(chunk: Dict, prefer_documents: bool) -> float:
    if not prefer_documents:
        return 0.0

    doc_type = _chunk_doc_type(chunk)
    meta = chunk.get("metadata") or {}
    document_kind = str(meta.get("document_kind") or "").lower()

    if doc_type == "gost":
        return 0.35
    if doc_type == "passport":
        if document_kind == "type_description":
            return 0.32
        if document_kind == "manual":
            return 0.30
        return 0.25
    if doc_type == "catalog":
        return -0.08
    return 0.0


def _rank_chunks(chunks: List[Dict], *, prefer_documents: bool) -> List[Dict]:
    ranked = []
    for chunk in chunks:
        item = dict(chunk)
        base_score = item.get("score", 0) or 0
        item["score"] = base_score + _document_boost(item, prefer_documents)
        ranked.append(item)
    return sorted(ranked, key=lambda x: x.get("score", 0), reverse=True)


def smart_search(
    store,
    product_detector,
    query_embedding,
    question: str,
    search_params: dict,
    question_type: dict,
    hybrid_retriever=None,
    use_hybrid: bool = True,
) -> List[Dict]:
    """Умный поиск с определением продукта"""
    top_k = search_params["top_k"]
    context_top_k = search_params.get("context_top_k", top_k)
    has_document_reference = _has_document_reference(question)
    prefer_documents = has_document_reference or question_type.get("is_attribute", False)

    if has_document_reference:
        mode = "гибридный BM25+FAISS" if use_hybrid and hybrid_retriever else "векторный FAISS"
        _safe_print(
            f"[DEBUG] Обнаружена ссылка на документ/стандарт — используем {mode} без ProductDetector"
        )
        results = _retrieval_search(
            store,
            hybrid_retriever,
            query_embedding,
            question,
            top_k,
            use_hybrid=use_hybrid,
        )
        return _rank_chunks(results, prefer_documents=True)[:context_top_k]

    product, product_score = product_detector.detect_product_from_question(
        question, query_embedding=query_embedding
    )
    
    if product and product_score > 0.4:
        _safe_print(f"[DEBUG] Определен продукт: '{product}' (уверенность: {product_score:.2f})")
        
        product_chunks = product_detector.search_chunks_by_product(
            product, top_k=15, query_embedding=query_embedding, query_text=question
        )

        if product_chunks:
            _safe_print(f"[DEBUG] Найдено {len(product_chunks)} чанков по продукту")

            hybrid_label = "гибридный" if use_hybrid and hybrid_retriever else "векторный"
            _safe_print(f"[DEBUG] Дополнительный {hybrid_label} поиск, top_k={top_k}")
            vector_results = _retrieval_search(
                store,
                hybrid_retriever,
                query_embedding,
                question,
                top_k,
                use_hybrid=use_hybrid,
            )

            by_id: Dict[str, Dict] = {}
            for chunk in product_chunks:
                chunk_id = chunk.get("chunk_id")
                if not chunk_id:
                    continue
                item = dict(chunk)
                # Если продукт уже определён, его собственные чанки должны остаться
                # в контексте даже при сильных нормативных совпадениях BM25.
                item["score"] = (item.get("score", 0) or 0) + 0.45
                by_id[chunk_id] = item

            for chunk in vector_results:
                chunk_id = chunk.get("chunk_id")
                if not chunk_id:
                    continue
                prev = by_id.get(chunk_id)
                if prev is None or chunk.get("score", 0) > prev.get("score", 0):
                    by_id[chunk_id] = chunk

            unique_chunks = _rank_chunks(
                list(by_id.values()), prefer_documents=prefer_documents
            )
            return unique_chunks[:context_top_k]
    
    mode = "гибридный BM25+FAISS" if use_hybrid and hybrid_retriever else "векторный FAISS"
    _safe_print(f"[DEBUG] Используем {mode} поиск")
    results = _retrieval_search(
        store,
        hybrid_retriever,
        query_embedding,
        question,
        top_k,
        use_hybrid=use_hybrid,
    )
    return _rank_chunks(results, prefer_documents=prefer_documents)[:context_top_k]


class AdvancedChatbot:
    """Продвинутый чатбот с определением продуктов и классификацией вопросов"""
    
    # Слова приветствия
    GREETING_WORDS = {
        'привет', 'здравствуй', 'здравствуйте', 'добрый день', 'добрый вечер', 
        'доброе утро', 'добрый', 'приветствую', 'хай', 'хэй', 'hello', 'hi', 
        'hey', 'салют', 'здарова', 'здорово', 'йо', 'ку', 'хола', 'бонжур'
    }
    
    # Ответы на приветствия
    GREETING_RESPONSES = [
        "Здравствуйте! Я консультант по оборудованию. Чем могу помочь?",
        "Добрый день! Готов ответить на ваши вопросы об оборудовании.",
        "Приветствую! Задавайте вопросы о нашей продукции.",
    ]
    
    def __init__(self, config_path: str = None):
        try:
            # Используем фиксированный путь без Unicode символов
            # чтобы избежать проблем с FAISS и другими библиотеками
            data_dir = r'C:\temp\chatbot'
            
            # Определяем путь к конфигу
            if config_path is None:
                # Пытаемся найти config.yaml в проекте (относительно этого файла)
                current_file = os.path.abspath(__file__)
                # Путь: back/chatbot/api/chatbot_core/chatbot.py -> back/project/config.yaml
                # chatbot_core -> api -> chatbot -> back -> project
                project_root = os.path.normpath(os.path.join(os.path.dirname(current_file), '..', '..', '..', 'project'))
                project_config = os.path.normpath(os.path.join(project_root, 'config.yaml'))
                
                if os.path.exists(project_config):
                    config_path = project_config
                    _safe_print(f"[INFO] Using config from project: {config_path}")
                else:
                    # Fallback на старый путь
                    config_path = os.path.join(data_dir, 'config.yaml')
                    _safe_print(f"[WARNING] Project config not found at {project_config}, using: {config_path}")
            elif not os.path.exists(config_path):
                _safe_print(f"[WARNING] Config path does not exist: {config_path}, trying project config...")
                # Пытаемся найти в проекте
                current_file = os.path.abspath(__file__)
                project_root = os.path.normpath(os.path.join(os.path.dirname(current_file), '..', '..', '..', 'project'))
                project_config = os.path.normpath(os.path.join(project_root, 'config.yaml'))
                if os.path.exists(project_config):
                    config_path = project_config
                    _safe_print(f"[INFO] Using config from project: {config_path}")
                else:
                    config_path = os.path.join(data_dir, 'config.yaml')
                    _safe_print(f"[WARNING] Using fallback config: {config_path}")
            
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)

            config_home = os.path.dirname(os.path.abspath(config_path))
            faiss_cfg = self.config.get("faiss") or {}
            index_rel = faiss_cfg.get("index_path", "data/faiss_index.bin")
            chunks_rel = faiss_cfg.get("chunks_path", "data/chunks.json")
            index_path = _resolve_under_config_dir(config_home, index_rel)
            chunks_path = _resolve_under_config_dir(config_home, chunks_rel)

            legacy_index = os.path.join(data_dir, "faiss_index.bin")
            legacy_chunks = os.path.join(data_dir, "chunks.json")
            if not os.path.isfile(chunks_path) and os.path.isfile(legacy_chunks):
                _safe_print(f"[INFO] chunks.json не найден по {chunks_path}, используем legacy: {legacy_chunks}")
                chunks_path = legacy_chunks
            if not os.path.isfile(index_path) and os.path.isfile(legacy_index):
                _safe_print(f"[INFO] faiss_index.bin не найден по {index_path}, используем legacy: {legacy_index}")
                index_path = legacy_index

            if not os.path.isfile(chunks_path):
                raise FileNotFoundError(f"Нет файла чанков: {chunks_path}")
            if not os.path.isfile(index_path):
                raise FileNotFoundError(
                    f"Нет FAISS-индекса: {index_path}. Соберите его: cd back/project/data && python build.py"
                )

            index_path, chunks_path = _faiss_readable_paths(index_path, chunks_path)
            
            # Логируем параметры LLM для отладки
            llm_config = self.config.get("llm", {})
            _safe_print(f"[INFO] LLM Config loaded:")
            _safe_print(f"[INFO]   base_url: {llm_config.get('base_url', 'NOT SET')}")
            _safe_print(f"[INFO]   model: {llm_config.get('model', 'NOT SET')}")
            _safe_print(f"[INFO]   temperature: {llm_config.get('temperature', 'NOT SET')}")
            _safe_print(f"[INFO]   max_tokens: {llm_config.get('max_tokens', 'NOT SET')}")
            _safe_print(f"[INFO]   timeout: {llm_config.get('timeout', 'NOT SET')}")
            
            # Инициализируем компоненты
            self.embedder = EmbeddingModel(self.config["embeddings"]["model_name"])
            
            _safe_print(f"[INFO] Loading index from: {index_path}")
            _safe_print(f"[INFO] Loading chunks from: {chunks_path}")

            active_doc_keys = None
            try:
                from ..services.knowledge_version import KnowledgeVersionService

                with open(chunks_path, "r", encoding="utf-8") as cf:
                    chunks_for_sync = json.load(cf).get("chunks") or []
                KnowledgeVersionService.ensure_synced_from_chunks(chunks_for_sync)
                active_doc_keys = set(KnowledgeVersionService.get_active_document_keys())
                kb_stats = KnowledgeVersionService.stats()
                _safe_print(
                    f"[INFO] Knowledge base registry: {kb_stats['active']} active / "
                    f"{kb_stats['total']} total documents"
                )
            except Exception as kb_exc:
                _safe_print(f"[WARNING] Knowledge versioning unavailable: {kb_exc}")

            self.store = VectorStore(
                index_path, chunks_path, active_doc_keys=active_doc_keys
            )
            self.hybrid = HybridRetriever(self.store)
            self.use_hybrid_search = True
            _safe_print("[INFO] HybridRetriever (BM25 + FAISS) initialized")
            
            # Проверяем наличие всех необходимых параметров
            required_params = ['base_url', 'model', 'temperature', 'max_tokens']
            missing_params = [p for p in required_params if p not in llm_config or not llm_config[p]]
            if missing_params:
                _safe_print(f"[ERROR] Missing required LLM parameters: {missing_params}")
                raise ValueError(f"Missing required LLM parameters: {missing_params}")
            
            self.llm = LLMClient(**llm_config)
            _safe_print(f"[INFO] LLMClient initialized with model: {self.llm.model}, base_url: {self.llm.client.base_url}")
            
            # Инициализируем детектор продуктов и классификатор
            self.product_detector = ProductDetector(self.store, self.embedder)
            self.classifier = QuestionClassifier(self.embedder)
            
            self.fallback = self.config["messages"]["fallback"]
            self.threshold = self.config["faiss"]["confidence_threshold"]
            self.top_k = self.config["faiss"]["top_k"]
            self.last_chunks = []
            self.last_llm_elapsed_ms = 0.0
            
            _safe_print(f"[INFO] Chatbot initialized successfully")
            _safe_print(f"[INFO] Total products: {len(self.product_detector.extract_product_names())}")
            
        except Exception as e:
            _safe_print(f"[ERROR] Error initializing chatbot: {e}")
            import traceback
            traceback.print_exc()
            self.config = None
    
    def is_greeting(self, text: str) -> bool:
        """Проверяет, является ли сообщение приветствием"""
        text_lower = text.lower().strip()
        
        # Пытаемся исправить двойную кодировку (Windows console issue)
        try:
            # Если текст был дважды закодирован в UTF-8
            fixed_text = text.encode('latin-1').decode('utf-8').lower().strip()
            _safe_print(f"[DEBUG] Fixed encoding: '{fixed_text}'")
        except (UnicodeDecodeError, UnicodeEncodeError):
            fixed_text = text_lower
        
        # Проверяем оба варианта
        texts_to_check = [text_lower, fixed_text]
        
        for check_text in texts_to_check:
            # Проверяем точное совпадение
            if check_text in self.GREETING_WORDS:
                _safe_print(f"[DEBUG] Exact greeting match: '{check_text}'")
                return True
            
            # Проверяем, начинается ли с приветствия
            for greeting in self.GREETING_WORDS:
                if check_text.startswith(greeting):
                    rest = check_text[len(greeting):]
                    if not rest or rest[0] in ' !.,?':
                        _safe_print(f"[DEBUG] Starts with greeting: '{greeting}'")
                        return True
        
        return False
    
    def get_greeting_response(self) -> str:
        """Возвращает случайный ответ на приветствие"""
        import random
        return random.choice(self.GREETING_RESPONSES)

    def generate_response(self, question: str) -> str:
        """Генерирует ответ на вопрос"""
        if self.config is None:
            return "Извините, чатбот временно недоступен."
        
        try:
            # Логируем входящий вопрос для отладки
            _safe_print(f"[DEBUG] Получен вопрос: '{question}' (длина: {len(question)})")
            
            # Проверяем, является ли сообщение приветствием
            is_greet = self.is_greeting(question)
            _safe_print(f"[DEBUG] is_greeting={is_greet}, question.lower()='{question.lower().strip()}'")
            
            if is_greet:
                _safe_print(f"[DEBUG] Обнаружено приветствие: '{question}'")
                return self.get_greeting_response()
            
            # Классифицируем вопрос
            question_type = self.classifier.classify(question)
            _safe_print(f"[DEBUG] Тип вопроса: {question_type['main_type']}, уверенность: {question_type['confidence']:.2f}")
            
            # Настраиваем параметры поиска
            search_params = adjust_search_parameters(question_type, self.top_k, self.threshold)
            
            # Кодируем вопрос
            query_embedding = self.embedder.encode(question)
            
            # Умный поиск
            results = smart_search(
                self.store, 
                self.product_detector, 
                query_embedding, 
                question, 
                search_params, 
                question_type,
                hybrid_retriever=self.hybrid,
                use_hybrid=self.use_hybrid_search,
            )
            
            # Фильтрация по типу чанков (fallback если < 2 результатов — задача 1.3)
            if search_params["chunk_types_filter"] and results:
                unfiltered_results = results
                filtered_results = [
                    r for r in results
                    if r.get("chunk_type") in search_params["chunk_types_filter"]
                ]
                if len(filtered_results) >= 2:
                    results = filtered_results
                else:
                    _safe_print(
                        f"[WARNING] chunk_types_filter={search_params['chunk_types_filter']} "
                        f"оставил {len(filtered_results)} чанк(ов) (< 2) — fallback на полный "
                        f"список из {len(unfiltered_results)} чанков "
                        f"(тип вопроса: {question_type.get('main_type')})."
                    )
                    results = unfiltered_results
            
            _safe_print(f"[DEBUG] Найдено чанков: {len(results)}")
            
            if not results:
                _safe_print(
                    "[LLM] запрос к LM Studio НЕ выполняется: нет чанков после поиска "
                    "(проверьте FAISS/chunks и формулировку вопроса)."
                )
                return self.fallback
            
            self.last_chunks = results
            
            # Проверка threshold (кроме атрибутных вопросов)
            if not question_type["is_attribute"]:
                best = results[0]
                sc = best.get("score", 0)
                th = search_params["threshold"]
                if sc < th:
                    _safe_print(
                        f"[LLM] запрос к LM Studio НЕ выполняется: score={sc:.4f} < порога={th} "
                        f"(см. faiss.confidence_threshold в config.yaml; для атрибутных вопросов порог не применяется)."
                    )
                    return self.fallback
            
            _safe_print("[LLM] отправка в LM Studio: RAG-ответ (generate)...")
            # Генерация ответа
            answer = self.llm.generate(results, question, question_type)
            self.last_llm_elapsed_ms = getattr(self.llm, "last_elapsed_ms", 0.0) or 0.0
            if self.last_llm_elapsed_ms > 0:
                _safe_print(
                    f"[LLM] LM Studio: ответ получен за {self.last_llm_elapsed_ms / 1000:.2f} с "
                    f"(модель: {self.llm.model})"
                )
            if not (answer or "").strip():
                return self.fallback
            return answer
            
        except Exception as e:
            _safe_print(f"[ERROR] Ошибка при генерации ответа: {e}")
            import traceback
            traceback.print_exc()
            return "Извините, произошла ошибка при обработке запроса."


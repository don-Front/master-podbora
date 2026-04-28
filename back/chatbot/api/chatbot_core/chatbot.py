import os
import shutil
import yaml
from typing import List, Dict, Tuple

from .embeddings import EmbeddingModel
from .vector_store import VectorStore
from .llm_client import LLMClient
from .product_detector import ProductDetector
from .question_classifier import QuestionClassifier


def adjust_search_parameters(question_type: dict, top_k: int, threshold: float) -> dict:
    """Настраивает параметры поиска"""
    
    if question_type["is_attribute"]:
        return {
            "top_k": 25,
            "threshold": 0.0,
            "chunk_types_filter": ["specifications", "basic_info", "applications"],
            "search_strategy": "aggressive"
        }
    elif question_type["is_description"]:
        return {
            "top_k": 15,
            "threshold": 0.4,
            "chunk_types_filter": ["basic_info", "applications"],
            "search_strategy": "normal"
        }
    elif question_type["is_comparison"]:
        return {
            "top_k": 20,
            "threshold": 0.3,
            "chunk_types_filter": ["specifications", "basic_info"],
            "search_strategy": "normal"
        }
    else:
        return {
            "top_k": top_k,
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
    print(f"[INFO] FAISS/chunks: копия в ASCII-путь для Windows: {mirror}")
    return dst_index, dst_chunks


def smart_search(store, product_detector, query_embedding, question: str, 
                search_params: dict, question_type: dict) -> List[Dict]:
    """Умный поиск с определением продукта"""
    
    product, product_score = product_detector.detect_product_from_question(question)
    
    if product and product_score > 0.4:
        print(f"[DEBUG] Определен продукт: '{product}' (уверенность: {product_score:.2f})")
        
        product_chunks = product_detector.search_chunks_by_product(product, top_k=15)
        
        if product_chunks:
            print(f"[DEBUG] Найдено {len(product_chunks)} чанков по продукту")
            
            vector_results = store.search(query_embedding, search_params["top_k"], product_filter=None)
            
            all_chunks = product_chunks + vector_results
            
            unique_chunks = []
            seen_ids = set()
            for chunk in all_chunks:
                chunk_id = chunk.get("chunk_id")
                if chunk_id and chunk_id not in seen_ids:
                    seen_ids.add(chunk_id)
                    unique_chunks.append(chunk)
            
            unique_chunks.sort(key=lambda x: x.get("score", 0), reverse=True)
            return unique_chunks[:search_params["top_k"]]
    
    print("[DEBUG] Используем обычный векторный поиск")
    return store.search(query_embedding, search_params["top_k"], product_filter=None)


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
                    print(f"[INFO] Using config from project: {config_path}")
                else:
                    # Fallback на старый путь
                    config_path = os.path.join(data_dir, 'config.yaml')
                    print(f"[WARNING] Project config not found at {project_config}, using: {config_path}")
            elif not os.path.exists(config_path):
                print(f"[WARNING] Config path does not exist: {config_path}, trying project config...")
                # Пытаемся найти в проекте
                current_file = os.path.abspath(__file__)
                project_root = os.path.normpath(os.path.join(os.path.dirname(current_file), '..', '..', '..', 'project'))
                project_config = os.path.normpath(os.path.join(project_root, 'config.yaml'))
                if os.path.exists(project_config):
                    config_path = project_config
                    print(f"[INFO] Using config from project: {config_path}")
                else:
                    config_path = os.path.join(data_dir, 'config.yaml')
                    print(f"[WARNING] Using fallback config: {config_path}")
            
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
                print(f"[INFO] chunks.json не найден по {chunks_path}, используем legacy: {legacy_chunks}")
                chunks_path = legacy_chunks
            if not os.path.isfile(index_path) and os.path.isfile(legacy_index):
                print(f"[INFO] faiss_index.bin не найден по {index_path}, используем legacy: {legacy_index}")
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
            print(f"[INFO] LLM Config loaded:")
            print(f"[INFO]   base_url: {llm_config.get('base_url', 'NOT SET')}")
            print(f"[INFO]   model: {llm_config.get('model', 'NOT SET')}")
            print(f"[INFO]   temperature: {llm_config.get('temperature', 'NOT SET')}")
            print(f"[INFO]   max_tokens: {llm_config.get('max_tokens', 'NOT SET')}")
            print(f"[INFO]   timeout: {llm_config.get('timeout', 'NOT SET')}")
            
            # Инициализируем компоненты
            self.embedder = EmbeddingModel(self.config["embeddings"]["model_name"])
            
            print(f"[INFO] Loading index from: {index_path}")
            print(f"[INFO] Loading chunks from: {chunks_path}")
            
            self.store = VectorStore(index_path, chunks_path)
            
            # Проверяем наличие всех необходимых параметров
            required_params = ['base_url', 'model', 'temperature', 'max_tokens']
            missing_params = [p for p in required_params if p not in llm_config or not llm_config[p]]
            if missing_params:
                print(f"[ERROR] Missing required LLM parameters: {missing_params}")
                raise ValueError(f"Missing required LLM parameters: {missing_params}")
            
            self.llm = LLMClient(**llm_config)
            print(f"[INFO] LLMClient initialized with model: {self.llm.model}, base_url: {self.llm.client.base_url}")
            
            # Инициализируем детектор продуктов и классификатор
            self.product_detector = ProductDetector(self.store, self.embedder)
            self.classifier = QuestionClassifier(self.embedder)
            
            self.fallback = self.config["messages"]["fallback"]
            self.threshold = self.config["faiss"]["confidence_threshold"]
            self.top_k = self.config["faiss"]["top_k"]
            self.last_chunks = []
            
            print(f"[INFO] Chatbot initialized successfully")
            print(f"[INFO] Total products: {len(self.product_detector.extract_product_names())}")
            
        except Exception as e:
            print(f"[ERROR] Error initializing chatbot: {e}")
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
            print(f"[DEBUG] Fixed encoding: '{fixed_text}'")
        except (UnicodeDecodeError, UnicodeEncodeError):
            fixed_text = text_lower
        
        # Проверяем оба варианта
        texts_to_check = [text_lower, fixed_text]
        
        for check_text in texts_to_check:
            # Проверяем точное совпадение
            if check_text in self.GREETING_WORDS:
                print(f"[DEBUG] Exact greeting match: '{check_text}'")
                return True
            
            # Проверяем, начинается ли с приветствия
            for greeting in self.GREETING_WORDS:
                if check_text.startswith(greeting):
                    rest = check_text[len(greeting):]
                    if not rest or rest[0] in ' !.,?':
                        print(f"[DEBUG] Starts with greeting: '{greeting}'")
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
            print(f"[DEBUG] Получен вопрос: '{question}' (длина: {len(question)})")
            
            # Проверяем, является ли сообщение приветствием
            is_greet = self.is_greeting(question)
            print(f"[DEBUG] is_greeting={is_greet}, question.lower()='{question.lower().strip()}'")
            
            if is_greet:
                print(f"[DEBUG] Обнаружено приветствие: '{question}'")
                return self.get_greeting_response()
            
            # Классифицируем вопрос
            question_type = self.classifier.classify(question)
            print(f"[DEBUG] Тип вопроса: {question_type['main_type']}, уверенность: {question_type['confidence']:.2f}")
            
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
                question_type
            )
            
            # Фильтрация по типу чанков
            if search_params["chunk_types_filter"] and results:
                filtered_results = [
                    r for r in results 
                    if r.get("chunk_type") in search_params["chunk_types_filter"]
                ]
                if filtered_results:
                    results = filtered_results
            
            print(f"[DEBUG] Найдено чанков: {len(results)}")
            
            if not results:
                print(
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
                    print(
                        f"[LLM] запрос к LM Studio НЕ выполняется: score={sc:.4f} < порога={th} "
                        f"(см. faiss.confidence_threshold в config.yaml; для атрибутных вопросов порог не применяется)."
                    )
                    return self.fallback
            
            print("[LLM] отправка в LM Studio: RAG-ответ (generate)...")
            # Генерация ответа
            answer = self.llm.generate(results, question, question_type)
            if not (answer or "").strip():
                return self.fallback
            return answer
            
        except Exception as e:
            print(f"[ERROR] Ошибка при генерации ответа: {e}")
            import traceback
            traceback.print_exc()
            return "Извините, произошла ошибка при обработке запроса."


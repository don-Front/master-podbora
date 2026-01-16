import yaml
from embeddings import EmbeddingModel
from vector_store import VectorStore
from llm_client import LLMClient
import numpy as np
import re
from typing import Dict, List, Optional, Tuple
import time

def load_config():
    """Загружает конфигурацию из файла"""
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

class ProductDetector:
    def __init__(self, store: VectorStore, embedder: EmbeddingModel):
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
                if title and len(title) > 3:  # Минимальная длина названия
                    product_names.add(title)
        
        self.all_products = sorted(list(product_names))
        print(f"[INFO] Извлечено {len(self.all_products)} уникальных названий продуктов")
        return self.all_products
    
    def detect_product_from_question(self, question: str) -> Tuple[Optional[str], float]:
        """Определяет продукт из вопроса с помощью эмбеддингов"""
        try:
            # Извлекаем все уникальные названия продуктов
            products = self.extract_product_names()
            
            if not products:
                return None, 0.0
            
            # Кодируем вопрос
            question_embedding = self.embedder.encode(question)
            
            # Кодируем названия продуктов с кэшированием
            for product in products:
                if product not in self.product_embeddings:
                    self.product_embeddings[product] = self.embedder.encode(product)
            
            # Ищем наиболее похожий продукт
            best_product = None
            best_score = 0.0
            
            for product, product_emb in self.product_embeddings.items():
                # Нормализуем векторы
                question_norm = question_embedding / np.linalg.norm(question_embedding)
                product_norm = product_emb / np.linalg.norm(product_emb)
                
                # Косинусное сходство
                similarity = np.dot(question_norm, product_norm)
                
                if similarity > best_score:
                    best_score = similarity
                    best_product = product
            
            # Динамический порог уверенности
            threshold = 0.4  # Более низкий порог
            
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
        
        # Проверяем разные варианты написания
        product_variations = [
            product_lower,
            product_lower.replace("-", " "),
            product_lower.replace(" ", "-")
        ]
        
        for chunk in self.store.chunks:
            chunk_product = chunk.get("product_title", "").lower()
            
            # Проверяем частичное совпадение с любым вариантом
            match_found = False
            for variant in product_variations:
                if variant and (variant in chunk_product or chunk_product in variant):
                    match_found = True
                    break
            
            if match_found:
                # Более точный расчет score
                content = chunk.get("content", "").lower()
                score = 0.8  # Базовый score для совпадения по названию
                
                # Увеличиваем score если название продукта точно совпадает
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
        
        # Сортируем по score и ограничиваем количество
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

class QuestionClassifier:
    def __init__(self, embedder):
        self.embedder = embedder
        
        # Оптимизированные шаблоны вопросов
        self.question_templates = {
            "attribute": [
                "Какой параметр у оборудования",
                "Какие технические характеристики",
                "Размеры и габариты устройства",
                "Производительность и мощность",
                "Время работы от аккумулятора",
                "Напряжение питания прибора",
                "Диапазон измерений оборудования",
                "Точность и погрешность",
                "Температурный режим работы",
                "Давление и расход"
            ],
            "description": [
                "Что такое это оборудование",
                "Для чего предназначен прибор",
                "Общее описание устройства",
                "Основные функции и возможности",
                "Принцип работы оборудования"
            ],
            "comparison": [
                "Сравните модели между собой",
                "Чем отличается один от другого",
                "Какая модель лучше подходит",
                "Различия между устройствами"
            ],
            "selection": [
                "Как выбрать подходящий прибор",
                "Что порекомендуете для задачи",
                "Какое оборудование подойдет",
                "Критерии выбора устройства"
            ],
            "operation": [
                "Как использовать оборудование",
                "Инструкция по эксплуатации",
                "Настройка и монтаж прибора",
                "Обслуживание устройства"
            ]
        }
        
        self.template_embeddings = {}
        self.prepare_templates()
    
    def prepare_templates(self):
        """Подготавливает эмбеддинги для шаблонов вопросов"""
        for q_type, templates in self.question_templates.items():
            self.template_embeddings[q_type] = self.embedder.encode_batch(templates)
    
    def classify(self, question: str) -> dict:
        """Классифицирует вопрос"""
        try:
            question_embedding = self.embedder.encode(question)
            
            scores = {}
            for q_type, type_embeddings in self.template_embeddings.items():
                max_similarity = 0
                for template_emb in type_embeddings:
                    # Нормализация векторов
                    q_norm = question_embedding / np.linalg.norm(question_embedding)
                    t_norm = template_emb / np.linalg.norm(template_emb)
                    
                    similarity = np.dot(q_norm, t_norm)
                    max_similarity = max(max_similarity, similarity)
                scores[q_type] = max_similarity
            
            if not scores:
                return self.keyword_classify(question)
            
            main_type = max(scores, key=scores.get)
            main_score = scores[main_type]
            
            # Динамический порог
            threshold = 0.25
            
            return {
                "is_attribute": main_type == "attribute" and main_score > threshold,
                "is_description": main_type == "description" and main_score > threshold,
                "is_comparison": main_type == "comparison" and main_score > threshold,
                "is_selection": main_type == "selection" and main_score > threshold,
                "is_operation": main_type == "operation" and main_score > threshold,
                "confidence": main_score,
                "main_type": main_type
            }
        except Exception as e:
            print(f"[ERROR] Ошибка классификации: {e}")
            return self.keyword_classify(question)
    
    def keyword_classify(self, question: str) -> dict:
        """Классификация по ключевым словам"""
        q_lower = question.lower()
        
        # Паттерны для атрибутных вопросов
        attribute_patterns = [
            r'какой\s+[\w-]+', r'какое\s+[\w-]+', r'какая\s+[\w-]+', 
            r'какие\s+[\w-]+', r'сколько\s+[\w-]+',
            r'диаметр', r'давление', r'расход', r'скорость', r'погрешность',
            r'температура', r'диапазон', r'размер', r'вес', r'мощность',
            r'напряжение', r'время', r'час', r'автоном', r'работ'
        ]
        
        for pattern in attribute_patterns:
            if re.search(pattern, q_lower):
                return {
                    "is_attribute": True,
                    "is_description": False,
                    "is_comparison": False,
                    "is_selection": False,
                    "is_operation": False,
                    "confidence": 0.6,
                    "main_type": "attribute"
                }
        
        # Другие типы
        if any(word in q_lower for word in ["что такое", "описание", "назначение"]):
            return {
                "is_attribute": False,
                "is_description": True,
                "is_comparison": False,
                "is_selection": False,
                "is_operation": False,
                "confidence": 0.7,
                "main_type": "description"
            }
        
        # По умолчанию
        return {
            "is_attribute": False,
            "is_description": True,
            "is_comparison": False,
            "is_selection": False,
            "is_operation": False,
            "confidence": 0.3,
            "main_type": "description"
        }

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

def smart_search(store, product_detector, query_embedding, question: str, 
                search_params: dict, question_type: dict) -> List[Dict]:
    """Умный поиск с определением продукта"""
    
    # Шаг 1: Определяем продукт из вопроса
    product, product_score = product_detector.detect_product_from_question(question)
    
    if product and product_score > 0.4:  # Более низкий порог
        print(f"[DEBUG] Определен продукт: '{product}' (уверенность: {product_score:.2f})")
        
        # Шаг 2: Ищем чанки по продукту
        product_chunks = product_detector.search_chunks_by_product(product, top_k=15)
        
        if product_chunks:
            print(f"[DEBUG] Найдено {len(product_chunks)} чанков по продукту")
            
            # Шаг 3: Векторный поиск для уточнения
            vector_results = store.search(query_embedding, search_params["top_k"], product_filter=None)
            
            # Объединяем результаты, отдавая приоритет чанкам по продукту
            all_chunks = product_chunks + vector_results
            
            # Убираем дубликаты по chunk_id
            unique_chunks = []
            seen_ids = set()
            for chunk in all_chunks:
                chunk_id = chunk.get("chunk_id")
                if chunk_id and chunk_id not in seen_ids:
                    seen_ids.add(chunk_id)
                    unique_chunks.append(chunk)
            
            # Сортируем по релевантности
            unique_chunks.sort(key=lambda x: x.get("score", 0), reverse=True)
            return unique_chunks[:search_params["top_k"]]
    
    # Шаг 4: Обычный векторный поиск
    print("[DEBUG] Используем обычный векторный поиск")
    return store.search(query_embedding, search_params["top_k"], product_filter=None)

def extract_parameter_keywords(question: str) -> List[str]:
    """Извлекает ключевые слова параметров из вопроса"""
    stop_words = {
        "какой", "какая", "какие", "какое", "каков", "у", "для", "что", "чем",
        "как", "где", "когда", "сколько", "от", "до", "и", "или", "но", "же",
        "в", "на", "с", "по", "о", "об", "из", "за", "под", "над", "при",
        "а", "то", "не", "ни", "да", "нет", "ли", "же", "ведь", "вот", "мол"
    }
    
    # Извлекаем слова
    words = re.findall(r'\b[\w-]+\b', question.lower())
    
    # Фильтруем
    keywords = []
    for word in words:
        if word not in stop_words and len(word) > 2:
            keywords.append(word)
    
    # Расширяем синонимами
    synonyms = {
        "автоном": ["автономный", "автономность"],
        "работ": ["работа", "рабочий"],
        "питани": ["питание", "питательный"],
        "источник": ["источников"],
        "встроен": ["встроенный"],
        "час": ["часов", "часа"],
        "диаметр": ["dn", "размер"],
        "давление": ["давл", "бар"],
        "расход": ["поток", "объем"],
        "температура": ["темп", "градус"],
        "погрешность": ["точность", "ошибка"],
        "мощность": ["потребление", "энергия"],
        "напряжение": ["вольт", "v"]
    }
    
    expanded_keywords = list(keywords)
    for keyword in keywords:
        for base, syn_list in synonyms.items():
            if base in keyword or keyword in base:
                expanded_keywords.extend(syn_list)
    
    return list(set(expanded_keywords))

def main():
    config = load_config()
    embedder = EmbeddingModel(config["embeddings"]["model_name"])
    store = VectorStore(config["faiss"]["index_path"], config["faiss"]["chunks_path"])
    llm = LLMClient(**config["llm"])
    
    # Инициализируем детектор продуктов и классификатор
    product_detector = ProductDetector(store, embedder)
    classifier = QuestionClassifier(embedder)
    
    fallback = config["messages"]["fallback"]
    threshold = config["faiss"]["confidence_threshold"]
    top_k = config["faiss"]["top_k"]
    last_chunks = []

    print("🤖 Консольный чат запущен")
    print("Введите вопрос или exit для выхода\n")
    
    # Показываем информацию о системе
    sample_products = product_detector.extract_product_names()[:5]
    if sample_products:
        print("Система знает о следующих продуктах (первые 5):")
        for i, product in enumerate(sample_products, 1):
            print(f"  {i}. {product}")
        print(f"Всего продуктов в базе: {len(product_detector.all_products)}\n")

    while True:
        question = input("Вы: ").strip()
        if not question:
            continue
        if question.lower() in ["exit", "выход", "quit"]:
            print("👋 Завершение работы")
            break

        start_time = time.time()
        
        try:
            # Определяем тип вопроса
            question_type = classifier.classify(question)
            
            print(f"\n[DEBUG] Тип вопроса: {question_type['main_type']}")
            print(f"[DEBUG] Уверенность: {question_type['confidence']:.2f}")

            # Настройка поиска
            search_params = adjust_search_parameters(question_type, top_k, threshold)
            
            # Извлекаем ключевые слова параметров
            param_keywords = extract_parameter_keywords(question)
            if param_keywords:
                print(f"[DEBUG] Ключевые слова: {', '.join(param_keywords[:5])}")

            # Поиск
            query_embedding = embedder.encode(question)
            
            results = smart_search(store, product_detector, query_embedding, 
                                 question, search_params, question_type)
            
            # Фильтрация по типу чанков
            if search_params["chunk_types_filter"] and results:
                filtered_results = []
                for r in results:
                    if r.get("chunk_type") in search_params["chunk_types_filter"]:
                        filtered_results.append(r)
                
                if filtered_results:
                    results = filtered_results
                elif question_type["is_attribute"]:
                    print("[DEBUG] Нет чанков нужного типа, используем все найденные")
            
            print(f"[DEBUG] Найдено чанков: {len(results)}")
            
            if results:
                print(f"[DEBUG] Лучший score: {results[0].get('score', 0):.3f}")
                
                # Информация о типах чанков
                chunk_types = {}
                for r in results[:5]:
                    c_type = r.get("chunk_type", "unknown")
                    chunk_types[c_type] = chunk_types.get(c_type, 0) + 1
                
                if chunk_types:
                    type_info = ", ".join([f"{k}: {v}" for k, v in chunk_types.items()])
                    print(f"[DEBUG] Типы чанков: {type_info}")
            
            # Если ничего не найдено
            if not results:
                print(f"\n🤖 {fallback}\n")
                continue

            last_chunks = results

            # Проверка threshold (кроме атрибутных вопросов)
            if not question_type["is_attribute"] and results:
                best = results[0]
                if best.get("score", 0) < search_params["threshold"]:
                    print(f"\n🤖 {fallback}\n")
                    continue

            # Генерация ответа
            print("[DEBUG] Генерация ответа...")
            answer = llm.generate(results, question, question_type)

            elapsed_time = time.time() - start_time
            print(f"[DEBUG] Время обработки: {elapsed_time:.2f} сек")

            # Вывод ответа
            print(f"\n🤖 {answer}\n")
            
        except Exception as e:
            print(f"\n❌ Произошла ошибка: {e}")
            print("Попробуйте переформулировать вопрос или обратиться в поддержку.\n")

if __name__ == "__main__":
    main()
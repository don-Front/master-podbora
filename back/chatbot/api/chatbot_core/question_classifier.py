import numpy as np
import re


class QuestionClassifier:
    def __init__(self, embedder):
        self.embedder = embedder
        
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
                "Давление и расход",
                "Для какой измеряемой среды газ или жидкость предназначен прибор",
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
                    q_norm = question_embedding / np.linalg.norm(question_embedding)
                    t_norm = template_emb / np.linalg.norm(template_emb)
                    similarity = np.dot(q_norm, t_norm)
                    max_similarity = max(max_similarity, similarity)
                scores[q_type] = max_similarity
            
            if not scores:
                return self.keyword_classify(question)
            
            main_type = max(scores, key=scores.get)
            main_score = scores[main_type]
            
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
        
        attribute_patterns = [
            r'какой\s+[\w-]+', r'какое\s+[\w-]+', r'какая\s+[\w-]+', 
            r'какие\s+[\w-]+', r'сколько\s+[\w-]+',
            r'диаметр', r'давление', r'расход', r'скорость', r'погрешность',
            r'температура', r'диапазон', r'размер', r'вес', r'мощность',
            r'напряжение', r'время', r'час', r'автоном', r'работ',
            r'сред[аыуе]', r'измеряем',
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
        
        return {
            "is_attribute": False,
            "is_description": True,
            "is_comparison": False,
            "is_selection": False,
            "is_operation": False,
            "confidence": 0.3,
            "main_type": "description"
        }


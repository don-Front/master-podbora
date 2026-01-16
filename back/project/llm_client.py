from openai import OpenAI
from typing import List, Dict, Optional
import re

class LLMClient:
    def __init__(self, base_url: str, model: str, temperature: float, max_tokens: int):
        self.client = OpenAI(
            base_url=base_url,
            api_key="lm-studio"
        )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @staticmethod
    def build_context(chunks: List[Dict]) -> str:
        """Строит контекст из чанков с приоритизацией"""
        blocks = []
        for c in chunks:
            # Добавляем релевантность для отладки
            score_info = f" (релевантность: {c.get('score', 0):.2f})" if 'score' in c else ""
            
            block = f"""
[Чанк {c.get('chunk_id', 'N/A')}{score_info}]
Продукт: {c.get("product_title", "Не указано")}
Тип информации: {c.get("chunk_type", "Не указан")}

{c.get("content", "Пустой контент")}
""".strip()
            blocks.append(block)
        return "\n\n" + "="*50 + "\n\n".join(blocks) + "\n" + "="*50

    def extract_keywords(self, question: str) -> List[str]:
        """Извлекает ключевые слова из вопроса для поиска в контексте"""
        # Удаляем стоп-слова и выделяем существительные/прилагательные
        stop_words = {"какой", "какая", "какие", "какое", "каков", "у", "для", "что", "чем", "как", "где", "когда"}
        
        # Разбиваем вопрос на слова
        words = re.findall(r'\b[\w-]+\b', question.lower())
        
        # Фильтруем стоп-слова и короткие слова
        keywords = []
        for word in words:
            if (word not in stop_words and 
                len(word) > 2 and 
                not word.isdigit()):
                keywords.append(word)
        
        # Добавляем возможные синонимы для технических терминов
        synonyms = {
            "диаметр": ["dn", "размер", "проход"],
            "давление": ["давл", "p", "бар"],
            "расход": ["поток", "объем", "скорость", "м3"],
            "температура": ["темп", "t", "градус"],
            "погрешность": ["точность", "ошибка", "отклонение", "допуск"],
            "диапазон": ["предел", "интервал", "от и до"],
            "габарит": ["размер", "величина", "место"],
            "вес": ["масса", "кг"],
            "мощность": ["потребление", "энергия", "ватт"]
        }
        
        # Расширяем ключевые слова синонимами
        expanded_keywords = []
        for keyword in keywords:
            expanded_keywords.append(keyword)
            for main_word, syn_list in synonyms.items():
                if keyword in main_word or main_word in keyword:
                    expanded_keywords.extend(syn_list)
        
        return list(set(expanded_keywords))

    def generate(self, chunks: List[Dict], question: str, question_type: dict) -> str:
        context = self.build_context(chunks)
        
        # Определяем продукт из чанков
        products_in_context = set(chunk.get("product_title", "") for chunk in chunks)
        main_product = self._extract_main_product(products_in_context)
        
        base_prompt = f"""
Ты — технический консультант компании.
Твой ответ должен быть основан ТОЛЬКО на предоставленном контексте.
Если информации нет в контексте — честно скажи об этом.

ОСНОВНОЙ ПРОДУКТ: {main_product if main_product else "Не определен"}

КОНТЕКСТ:
{context}

ВОПРОС КЛИЕНТА: {question}

"""
        
        # Специализированные инструкции
        if question_type.get("is_attribute", False):
            prompt = base_prompt + """
ЗАДАЧА: Найти точные значения параметров.
1. ВНИМАТЕЛЬНО просмотри весь контекст
2. Найди все упоминания параметра из вопроса
3. Если параметр найден — укажи точное значение с единицами
4. Если есть разные значения для разных моделей — перечисли все
5. Если параметр не найден — так и скажи

ОТВЕТ (будь точен и краток):
"""
        else:
            prompt = base_prompt + """
ЗАДАЧА: Ответить на вопрос клиента.
1. Используй информацию из контекста
2. Будь информативен, но лаконичен
3. Структурируй ответ если это уместно
4. Если информации недостаточно — признай это

ОТВЕТ:
"""
        
        return self._call_llm(prompt)
    
    def _extract_main_product(self, products: set) -> str:
        """Извлекает основной продукт из набора"""
        if not products:
            return ""
        
        # Убираем пустые строки
        products = {p for p in products if p}
        
        if len(products) == 1:
            return next(iter(products))
        
        # Если несколько продуктов, выбираем самый частый
        from collections import Counter
        product_counter = Counter(products)
        return product_counter.most_common(1)[0][0]
    def _build_specialized_prompt(self, context: str, question: str, 
                                 question_type: dict, keywords: List[str]) -> str:
        """Строит специализированный промпт для разных типов вопросов"""
        
        base_prompt = f"""
Ты — эксперт технической поддержки компании, специализирующийся на оборудовании для измерения расхода.
Ты обладаешь глубокими знаниями о продукции и готов помочь клиенту.

ИНСТРУКЦИИ:
1. Используй ТОЛЬКО информацию из предоставленного контекста
2. Если информация в контексте противоречива, укажи на это
3. Будь точен в цифрах и единицах измерения
4. Если информации недостаточно, честно признай это
5. Структурируй ответ для лучшего восприятия

КОНТЕКСТ ДЛЯ ПОИСКА:
{context}

КЛЮЧЕВЫЕ СЛОВА ДЛЯ ПОИСКА В КОНТЕКСТЕ: {', '.join(keywords)}

ВОПРОС КЛИЕНТА: {question}
"""
        
        # Специализированные инструкции для разных типов вопросов
        if question_type.get("is_attribute", False):
            return base_prompt + """

ЗАДАНИЕ ДЛЯ ТЕХНИЧЕСКИХ ПАРАМЕТРОВ:
1. ВНИМАТЕЛЬНО ищи запрашиваемый параметр в контексте
2. Если параметр найден:
   - Укажи ТОЧНОЕ значение с единицами измерения
   - Укажи источник (из какого чанка)
   - Если есть разные значения для разных моделей/модификаций - перечисли все
   - Объясни что означает этот параметр простыми словами
3. Если параметр не найден:
   - Честно скажи "Параметр не найден в технической документации"
   - Предложи альтернативные похожие параметры из контекста
   - Посоветуй где можно найти дополнительную информацию

ОТВЕТ КОНСУЛЬТАНТА (будь точен и информативен):
"""
        
        elif question_type.get("is_selection", False):
            return base_prompt + """

ЗАДАНИЕ ДЛЯ ПОДБОРА ОБОРУДОВАНИЯ:
1. Определи требования клиента из вопроса
2. Проанализируй варианты из контекста
3. Рекомендуй подходящий вариант с ОБОСНОВАНИЕМ
4. Укажи ключевые отличия моделей
5. Задай уточняющие вопросы если информации недостаточно

ОТВЕТ КОНСУЛЬТАНТА (предоставь обоснованные рекомендации):
"""
        
        elif question_type.get("is_application", False):
            return base_prompt + """

ЗАДАНИЕ ДЛЯ ВОПРОСОВ ПО ПРИМЕНЕНИЮ:
1. Опиши сферы применения оборудования из контекста
2. Укажи особенности монтажа и эксплуатации
3. Перечисли ограничения и требования
4. Дай практические советы по использованию

ОТВЕТ КОНСУЛЬТАНТА (практические рекомендации):
"""
        
        elif question_type.get("is_troubleshooting", False):
            return base_prompt + """

ЗАДАНИЕ ДЛЯ УСТРАНЕНИЯ НЕИСПРАВНОСТЕЙ:
1. Определи возможные причины проблемы
2. Предложи пошаговую диагностику
3. Укажи способы решения
4. Посоветуй когда обращаться к специалистам

ОТВЕТ КОНСУЛЬТАНТА (практические решения):
"""
        
        elif question_type.get("is_description", False):
            return base_prompt + """

ЗАДАНИЕ ДЛЯ ОПИСАТЕЛЬНЫХ ВОПРОСОВ:
1. Дай полное описание оборудования
2. Укажи ключевые особенности и преимущества
3. Структурируй информацию по категориям
4. Будь информативен, но лаконичен

ОТВЕТ КОНСУЛЬТАНТА (структурированное описание):
"""
        
        else:
            return base_prompt + """

ЗАДАНИЕ ДЛЯ ОБЩИХ ВОПРОСОВ:
1. Дай полный ответ на вопрос клиента
2. Используй информацию из контекста
3. Структурируй ответ для удобства чтения
4. Будь дружелюбен и профессиональен

ОТВЕТ КОНСУЛЬТАНТА (развернутый и полезный ответ):
"""

    def _call_llm(self, prompt: str) -> str:
        """Вызывает LLM API"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                messages=[
                    {
                        "role": "system", 
                        "content": "Ты технический эксперт, помогающий клиентам с оборудованием."
                    },
                    {"role": "user", "content": prompt}
                ]
            )
            
            if response and response.choices:
                answer = response.choices[0].message.content.strip()
                
                # Пост-обработка ответа
                answer = self._post_process_answer(answer)
                return answer
            else:
                return "Извините, не удалось получить ответ от сервера."
                
        except Exception as e:
            print(f"Ошибка при генерации ответа: {e}")
            return "Извините, произошла ошибка при обработке запроса."

    def _post_process_answer(self, answer: str) -> str:
        """Пост-обработка ответа для улучшения качества"""
        # Удаляем повторяющиеся фразы
        lines = answer.split('\n')
        unique_lines = []
        seen_lines = set()
        
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped not in seen_lines:
                unique_lines.append(line)
                seen_lines.add(line_stripped)
        
        # Объединяем обратно
        processed = '\n'.join(unique_lines)
        
        # Убираем избыточные маркеры
        processed = re.sub(r'\n{3,}', '\n\n', processed)
        
        return processed.strip()

    def _generate_no_context_response(self, question_type: dict) -> str:
        """Генерирует ответ когда контекст не найден"""
        if question_type.get("is_attribute", False):
            return "📊 **Технические параметры:**\n\nК сожалению, не удалось найти техническую документацию по запрашиваемому параметру. Рекомендую:\n\n1. Проверить полное название оборудования\n2. Обратиться к официальной документации\n3. Связаться с технической поддержкой"
        
        return "💡 **Информация:**\n\nК сожалению, не удалось найти информацию по вашему запросу. Попробуйте:\n\n1. Переформулировать вопрос\n2. Указать конкретное название оборудования\n3. Задать более общий вопрос\n\nИли свяжитесь с нашей технической поддержкой для получения подробной информации."

    def format_answer(self, answer: str, question_type: dict, chunks: Optional[List[Dict]] = None) -> str:
        """Форматирует ответ для лучшей читаемости"""
        
        # Базовое форматирование с эмодзи
        if question_type.get("is_attribute", False):
            prefix = "📊 **Технические параметры:**\n\n"
        elif question_type.get("is_selection", False):
            prefix = "🔍 **Рекомендация по подбору:**\n\n"
        elif question_type.get("is_troubleshooting", False):
            prefix = "🔧 **Решение проблемы:**\n\n"
        elif question_type.get("is_application", False):
            prefix = "🛠️ **Применение и монтаж:**\n\n"
        elif question_type.get("is_description", False):
            prefix = "📋 **Описание оборудования:**\n\n"
        else:
            prefix = "💡 **Информация:**\n\n"
        
        # Добавляем информацию о релевантности если есть чанки
        if chunks and len(chunks) > 0:
            best_score = chunks[0].get('score', 0)
            if best_score < 0.3:
                prefix += f"*Примечание: информация найдена с низкой релевантностью ({best_score:.2f}), рекомендуем уточнить вопрос*\n\n"
        
        formatted_answer = prefix + answer
        
        # Добавляем разделитель и следующее предложение если ответ короткий
        if len(answer.split()) < 50:
            suggestions = self._get_followup_suggestions(question_type)
            if suggestions:
                formatted_answer += f"\n\n---\n\n{suggestions}"
        
        return formatted_answer

    def _get_followup_suggestions(self, question_type: dict) -> str:
        """Предлагает следующие логичные вопросы"""
        suggestions = []
        
        if question_type.get("is_attribute", False):
            suggestions = [
                "Также вас может интересовать рабочий диапазон давления",
                "Возможно нужна информация о температурных пределах",
                "Могу помочь с информацией о точности измерений"
            ]
        elif question_type.get("is_selection", False):
            suggestions = [
                "Для точного подбора уточните диапазон расхода",
                "Важна ли информация о требованиях к монтажу?",
                "Нужны данные о совместимости со средами?"
            ]
        
        if suggestions:
            return "💡 **Что еще узнать:**\n" + "\n".join(f"• {s}" for s in suggestions[:2])
        
        return ""

    def search_in_chunks(self, chunks: List[Dict], target_param: str) -> List[str]:
        """Ищет конкретный параметр в чанках (для отладки)"""
        found_values = []
        target_lower = target_param.lower()
        
        for chunk in chunks:
            content = chunk.get('content', '').lower()
            product = chunk.get('product_title', '')
            
            # Простой поиск по ключевым словам
            if target_lower in content:
                # Извлекаем строку с параметром
                lines = chunk.get('content', '').split('\n')
                for line in lines:
                    if target_lower in line.lower():
                        found_values.append(f"В продукте '{product}': {line.strip()}")
        
        return found_values
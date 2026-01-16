from openai import OpenAI
from typing import List, Dict
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
            score_info = f" (релевантность: {c.get('score', 0):.2f})" if 'score' in c else ""
            
            block = f"""
[Чанк {c.get('chunk_id', 'N/A')}{score_info}]
Продукт: {c.get("product_title", "Не указано")}
Тип информации: {c.get("chunk_type", "Не указан")}

{c.get("content", "Пустой контент")}
""".strip()
            blocks.append(block)
        return "\n\n" + "="*50 + "\n\n".join(blocks) + "\n" + "="*50

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
        
        products = {p for p in products if p}
        
        if len(products) == 1:
            return next(iter(products))
        
        from collections import Counter
        product_counter = Counter(products)
        return product_counter.most_common(1)[0][0] if product_counter else ""

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
                answer = self._post_process_answer(answer)
                return answer
            else:
                return "Извините, не удалось получить ответ от сервера."
                
        except Exception as e:
            print(f"Ошибка при генерации ответа: {e}")
            return "Извините, произошла ошибка при обработке запроса."

    def _post_process_answer(self, answer: str) -> str:
        """Пост-обработка ответа для улучшения качества"""
        lines = answer.split('\n')
        unique_lines = []
        seen_lines = set()
        
        for line in lines:
            line_stripped = line.strip()
            if line_stripped and line_stripped not in seen_lines:
                unique_lines.append(line)
                seen_lines.add(line_stripped)
        
        processed = '\n'.join(unique_lines)
        processed = re.sub(r'\n{3,}', '\n\n', processed)
        
        return processed.strip()


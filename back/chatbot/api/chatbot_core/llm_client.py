from openai import OpenAI
from typing import List, Dict, Any, Optional
import logging
import os
import re
import time

import httpx

from .rag_messages import MSG_REPHRASE, MSG_SERVER_ERROR, is_llm_system_error

logger = logging.getLogger(__name__)


_CHUNK_TYPE_LABELS = {
    "basic_info": "общая информация",
    "applications": "область применения",
    "specifications": "технические характеристики",
    "features": "особенности и преимущества",
    "section": "раздел",
}

_CITATION_INSTRUCTION = """
ЦИТИРОВАНИЕ:
- НЕ добавляй в текст ответа ссылки вида [Документ: …] — источники покажет интерфейс отдельно.
- Не выдумывай номера страниц и названия документов.
- Не пиши слова chunk, context, фрагмент — только готовый ответ клиенту.
"""


def _normalize_lm_base_url(base_url: str) -> str:
    """
    LM Studio (OpenAI-совместимый): базовый URL должен заканчиваться на /v1
    (частая ошибка в config: только http://host:1234 — без /v1 запросы не попадают в API).
    """
    u = (base_url or "").strip().rstrip("/")
    if not u:
        return u
    if u.endswith("/v1"):
        return u
    return f"{u}/v1"


def resolve_llm_api_key(api_key: Optional[str] = None) -> str:
    """Токен LM Studio: config llm.api_key → LM_STUDIO_API_KEY / LM_API_TOKEN → lm-studio."""
    for candidate in (
        api_key,
        os.environ.get("LM_STUDIO_API_KEY"),
        os.environ.get("LM_API_TOKEN"),
    ):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return "lm-studio"


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: int = 60,
        api_key: Optional[str] = None,
    ):
        base_url = _normalize_lm_base_url(base_url)
        resolved_key = resolve_llm_api_key(api_key)
        # trust_env=False: не подхватывать HTTP(S)_PROXY/socks из окружения —
        # иначе httpx падает на socks4:// и RAG не инициализируется.
        self.client = OpenAI(
            base_url=base_url,
            api_key=resolved_key,
            timeout=timeout,
            http_client=httpx.Client(trust_env=False, timeout=timeout),
        )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.last_elapsed_ms = 0.0
        self.last_error_kind: str | None = None

    def _fail(self, kind: str, message: str) -> str:
        self.last_error_kind = kind
        return message

    @staticmethod
    def _resolve_chunk_source(chunk: Dict) -> Dict[str, str]:
        """Метаданные источника для контекста и цитирования (задача 1.4)."""
        meta = chunk.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}

        document_name = (meta.get("document_name") or chunk.get("product_title") or "").strip()
        page_raw = meta.get("page_number", meta.get("page"))
        page = str(page_raw).strip() if page_raw is not None and str(page_raw).strip() else ""
        paragraph = (meta.get("paragraph") or meta.get("section_title") or "").strip()

        if not paragraph:
            chunk_type = chunk.get("chunk_type") or meta.get("type") or ""
            paragraph = _CHUNK_TYPE_LABELS.get(str(chunk_type), str(chunk_type)).strip()

        if not document_name:
            citation = "(источник не указан)"
            source_status = "не указан"
        elif page:
            citation = f"[Документ: {document_name}, стр. {page}]"
            source_status = "указан"
        elif paragraph:
            citation = f"[Документ: {document_name}, раздел «{paragraph}»]"
            source_status = "указан"
        elif meta.get("document_name"):
            citation = f"[Документ: {document_name}]"
            source_status = "указан"
        else:
            citation = f"[Документ: {document_name}]"
            source_status = "частично (без страницы/пункта)"

        return {
            "document_name": document_name or "не указан",
            "page": page or "не указана",
            "paragraph": paragraph or "не указан",
            "citation": citation,
            "source_status": source_status,
        }

    @staticmethod
    def build_context(chunks: List[Dict]) -> str:
        """Строит контекст из чанков с метаданными источника для цитирования."""
        blocks = []
        for c in chunks:
            score_info = f" (релевантность: {c.get('score', 0):.2f})" if "score" in c else ""
            src = LLMClient._resolve_chunk_source(c)

            block = f"""
[Фрагмент {c.get('chunk_id', 'N/A')}{score_info}]
Документ: {src['document_name']}
Страница: {src['page']}
Пункт/раздел: {src['paragraph']}
Ссылка для ответа: {src['citation']}
Продукт: {c.get("product_title", "Не указано")}
Тип информации: {c.get("chunk_type", "Не указан")}

{c.get("content", "Пустой контент")}
""".strip()
            blocks.append(block)
        return "\n\n" + "=" * 50 + "\n\n".join(blocks) + "\n" + "=" * 50

    def generate(self, chunks: List[Dict], question: str, question_type: dict) -> str:
        context = self.build_context(chunks)
        
        # Определяем продукт из чанков
        products_in_context = set(chunk.get("product_title", "") for chunk in chunks)
        main_product = self._extract_main_product(products_in_context)
        
        base_prompt = f"""
Ты — технический консультант. Ответь клиенту по-русски, только фактами из приведённого ниже контекста.
Если в контексте нет ответа — так и напиши коротко.

Не описывай ход рассуждений, не используй заголовок «Thinking Process», не пиши пошаговый разбор на английском,
не перечисляй роли (Role), задачи (Task), не ссылайся на «chunk» / «context» / «фрагмент» — клиент этого не должен видеть.
Отвечай строго на заданный вопрос: не добавляй смежные характеристики, сроки, модели или справочную информацию,
если пользователь прямо об этом не спрашивал.
Если в контексте несколько документов или продуктов, используй только те фрагменты, которые напрямую относятся к вопросу.
{_CITATION_INSTRUCTION}
ТЕРМИНЫ:
- Если в вопросе «среда» без уточнения «программная» — это измеряемая среда (газ/жидкость), для которой предназначен прибор.
- Не подменяй измеряемую среду программной средой, оболочкой или интерфейсом, если вопрос не про ПО явно.
ОСНОВНОЙ ПРОДУКТ: {main_product if main_product else "Не определен"}

КОНТЕКСТ:
{context}

ВОПРОС КЛИЕНТА: {question}

"""
        
        if question_type.get("is_definition", False):
            prompt = base_prompt + """
Сформулируй понятное определение для клиента:
1. Что это за оборудование.
2. Для чего оно предназначено.
3. Где или в каких задачах применяется, если это есть в контексте.

Пиши 2-4 коротких предложения без технической воды. Если в контексте есть только часть фактов — используй только её.
Не добавляй характеристики, поверку, сроки, документы или сравнения, если пользователь прямо не спрашивал.
Начинай сразу с ответа, без вступления.
"""
        elif question_type.get("is_attribute", False):
            prompt = base_prompt + """
Сформулируй ответ для клиента: только найденные в контексте значения параметров (с единицами измерения).
Если для разных модификаций значения различаются — перечисли по модификациям. Если параметра в тексте нет — напиши об этом.
Начинай сразу с ответа (списком или абзацами), без вступления про то, как ты анализируешь документ.
"""
        elif question_type.get("detected_products") and len(question_type["detected_products"]) >= 2:
            products_list = ", ".join(question_type["detected_products"])
            prompt = base_prompt + f"""
В вопросе несколько серий/продуктов: {products_list}.
Структурируй ответ ОТДЕЛЬНЫМИ блоками по каждой серии (заголовок — название серии, затем факты).
Если по какой-то серии в контексте нет данных — явно напиши об этом для этой серии.
Начинай сразу с ответа, без вступления.
"""
        else:
            prompt = base_prompt + """
Сформулируй ответ для клиента: по существу вопроса, по-русски, структурируй при необходимости списком.
Сохраняй в ответе ключевые термины, числа и обозначения из контекста (модели, ГОСТ, параметры) без искажений.
Если найден только частичный факт — ответь только найденной частью и явно не додумывай остальное.
Начинай сразу с ответа, без вступления и без описания своих шагов.
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

    @staticmethod
    def _strip_chain_of_thought(text: str) -> str:
        """Убирает видимый chain-of-thought (Thinking Process, теги thinking и т.п.)."""
        if not text:
            return ""
        t = re.sub(
            r"<think>.*?</think>\s*",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        t = re.sub(r"<thinking>.*?</thinking>\s*", "", t, flags=re.DOTALL | re.IGNORECASE)
        if not re.search(r"(?i)Thinking\s+Process:", t):
            return t.strip()

        # Типичный случай: после рассуждений идёт блок с параметрами на кириллице (маркированный список)
        param_start = re.compile(
            r"(?m)^\s*[\*•\-]\s*(?:\*\*)?"
            r"(?:Диаметр|Диапазон|Динамический|Пределы|Модификац|Габарит|Масса|Питание|Температур|"
            r"Давлен|Точност|Погрешност|Класс|Исполнен|Материал|Среда|Подключен|Выходн|Напряжен)[^\n]{0,120}",
            re.IGNORECASE,
        )
        m = param_start.search(t)
        if m:
            return t[m.start() :].strip()

        lines = t.splitlines()
        out: List[str] = []
        bad = re.compile(
            r"(?i)(thinking process|analyze the|scan context|extract parameters|"
            r"\*\*analyze|\*\*scan|\*\*extract|\*\*goal|\*\*role|\*\*task|chunk \d|the context)",
        )
        cyr = re.compile(r"[А-Яа-яЁё].{12,}")
        started = False
        for ln in lines:
            if bad.search(ln):
                continue
            if not started and cyr.search(ln) and not re.match(r"^\s*\d+\.\s*\*\*", ln.strip()):
                started = True
            if started:
                out.append(ln)
        if out:
            return "\n".join(out).strip()
        return t.strip()

    @staticmethod
    def _extract_assistant_text(message: Any) -> str:
        """
        Текст ответа ассистента: OpenAI-совместимые серверы (LM Studio, vLLM, Qwen)
        иногда кладут текст не только в message.content.
        """
        if message is None:
            return ""

        def _s(v: Optional[str]) -> str:
            if v is None:
                return ""
            return str(v).strip()

        text = _s(getattr(message, "content", None))
        if text:
            return text

        for attr in ("reasoning_content", "reasoning", "text"):
            t = _s(getattr(message, attr, None))
            if t:
                return t

        model_dump = getattr(message, "model_dump", None)
        if callable(model_dump):
            try:
                data = model_dump(mode="python")
            except TypeError:
                data = model_dump()
            if isinstance(data, dict):
                for key in ("content", "reasoning_content", "reasoning", "text", "response"):
                    t = _s(data.get(key) if isinstance(data.get(key), (str, type(None))) else None)
                    if t:
                        return t

        return ""

    def _call_llm(self, prompt: str) -> str:
        """Вызывает LLM API"""
        self.last_elapsed_ms = 0.0
        self.last_error_kind = None
        max_retries = 2
        retry_delay = 2
        
        # Логируем параметры запроса
        print(f"[DEBUG] LLM Request:")
        print(f"[DEBUG]   base_url: {self.client.base_url}")
        print(f"[DEBUG]   model: {self.model}")
        print(f"[DEBUG]   temperature: {self.temperature}")
        print(f"[DEBUG]   max_tokens: {self.max_tokens}")
        print(f"[DEBUG]   timeout: {self.timeout}")
        
        for attempt in range(max_retries + 1):
            try:
                start_time = time.time()
                print(f"[DEBUG] Sending request to LLM API (attempt {attempt + 1}/{max_retries + 1})...")
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Ты технический консультант по приборам. Пиши только готовый ответ клиенту на русском: "
                                "факты, списки, цифры из документации. "
                                "Не добавляй в текст ссылки [Документ: …] — источники покажет интерфейс. "
                                "Запрещено: Thinking Process, пошаговый разбор, "
                                "анализ на английском, заголовки Role/Task/Goal, упоминания chunk, context и фрагмент."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    timeout=self.timeout
                )
                
                elapsed_time = time.time() - start_time
                self.last_elapsed_ms = round(elapsed_time * 1000, 1)
                logger.info(
                    "[LLM] LM Studio: ответ за %.2f с (модель: %s, попытка %d/%d)",
                    elapsed_time,
                    self.model,
                    attempt + 1,
                    max_retries + 1,
                )
                
                if response and response.choices:
                    choice = response.choices[0]
                    msg = choice.message
                    finish = getattr(choice, "finish_reason", None)
                    answer = self._extract_assistant_text(msg)
                    answer = LLMClient._strip_chain_of_thought(answer)
                    answer = self._post_process_answer(answer)
                    if not answer:
                        print(
                            f"[WARNING] LLM пустой ответ (finish_reason={finish!r}). "
                            "Проверьте max_tokens в config.yaml и вывод модели в LM Studio."
                        )
                        return self._fail("rephrase", MSG_REPHRASE)
                    return answer
                else:
                    return self._fail("server", MSG_SERVER_ERROR)

            except Exception as e:
                error_msg = str(e).lower()
                is_timeout = "timeout" in error_msg or "timed out" in error_msg

                if is_timeout and attempt < max_retries:
                    print(f"[WARNING] Таймаут запроса (попытка {attempt + 1}/{max_retries + 1}). Повтор через {retry_delay} сек...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue

                print(f"Ошибка при генерации ответа: {e}")
                if is_timeout or is_llm_system_error(e):
                    return self._fail("server", MSG_SERVER_ERROR)
                return self._fail("rephrase", MSG_REPHRASE)

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


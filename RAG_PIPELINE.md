# RAG Pipeline — Turbo-Don Chatbot

**Назначение документа:** передать DeepSeek (или другому аналитику) полный контекст работы Retrieval-Augmented Generation в проекте чатбота Turbo-Don — от данных до ответа в UI. Документ описывает **фактическое состояние кода**, границы системы, инварианты, известные дефекты и план доработок.

**Связанные файлы в репозитории:**

| Файл | Роль |
|------|------|
| `DEEPSEEK_PROJECT_ANALYSIS.md` | Широкий аудит всего проекта (backend, FSM, frontend, интеграции) |
| `RAG_REFACTOR_PLAN.md` | Пошаговый план исправлений RAG (Этапы 1–5) |
| `TZ_chatbot_Turbo_Don.md` | Требования заказчика (FR-11, AC-04 и др.) |
| `.cursorrules` | Правила разработки (деплой, порты, не коммитить без согласия) |

**Ветка / снимок:** `feature/rag-refactor`, коммит «до шага 1.3 deepseek».  
**Уже внедрено:** задачи **1.1** (формула score), **1.2** (`top_k`).  
**Не внедрено:** задачи **1.3–1.5**, Этапы 2–5.

---

## 0. Что такое RAG в этом проекте (концептуально)

### 0.1. Определение

RAG здесь — **не** универсальный поиск по корпусу ГОСТ/паспортов/PDF. Это **узкий контур**:

> Пользователь задаёт вопрос на естественном языке → система находит релевантные **текстовые фрагменты (чанки)** из заранее подготовленной базы → передаёт их как **контекст** локальной LLM (LM Studio) → модель формулирует ответ **только на основе контекста**.

База знаний на текущий момент — **682 чанка**, **51 продукт**, источник — **карточки продуктов с сайта** `turbo-don.ru`. Упоминания ГОСТов (8.611, 14254 и т.д.) есть **внутри текста чанков**, но отдельного индекса нормативных документов **нет**.

### 0.2. Чем RAG **не** является в этом репозитории

| Контур | Модули | Отличие от RAG |
|--------|--------|----------------|
| Подбор расходомера по PDF/DOCX | `pdf_order_analysis.py`, FSM `order_pdf_request` | OCR + LLM → JSON спецификации → внешний `:8010`, не FAISS |
| Текстовый подбор | `order_specs_text.py` | Regex + LLM → тот же JSON, перехват до RAG |
| Подбор по параметрам (слайдер) | `fetchSearchEquipment`, `:8010` | Детерминированный API, не семантический поиск |
| Цена, заявки, верификация | `views.py`, `:8010` | FSM + внешние сервисы |

RAG вызывается только когда пользователь в состоянии **`start`** или **финальном** (`is_final`) пишет **обычный вопрос**, который **не** распознан как запрос на подбор оборудования (`looks_like_order_specs_request`).

### 0.3. Архитектурные слои

```
┌─────────────────────────────────────────────────────────────┐
│  Presentation   React ChatWidget.js  →  api.js (axios)      │
├─────────────────────────────────────────────────────────────┤
│  API / Routing  Django MessageViewSet.create()  views.py     │
├─────────────────────────────────────────────────────────────┤
│  Orchestration  get_chatbot() → AdvancedChatbot             │
│                 generate_response()  chatbot_core/chatbot.py│
├─────────────────────────────────────────────────────────────┤
│  Retrieval      QuestionClassifier, ProductDetector,        │
│                 VectorStore + FAISS                         │
├─────────────────────────────────────────────────────────────┤
│  Generation     LLMClient → LM Studio (OpenAI-compatible)   │
├─────────────────────────────────────────────────────────────┤
│  Knowledge      chunks.json + faiss_index.bin + config.yaml │
└─────────────────────────────────────────────────────────────┘
```

**Критично:** слои Retrieval и Knowledge **жёстко связаны** через инвариант порядка чанков (см. §3.4). Слой Orchestration **кэшируется** в процессе Daphne (см. §4.2).

---

## 1. База знаний: данные, индекс, инварианты

### 1.1. Артефакты

| Артефакт | Путь | В git | Назначение |
|----------|------|-------|------------|
| Чанки | `back/project/data/chunks.json` | да | Тексты + метаданные |
| FAISS-индекс | `back/project/data/faiss_index.bin` | **нет** (`*.bin` в `.gitignore`) | Векторы `content` |
| Конфиг | `back/project/config.yaml` | да | Модели, пороги, пути, LLM |
| Сборка индекса | `back/project/data/build.py` | да | chunks → embeddings → FAISS |
| Legacy mirror | `C:\temp\chatbot\` | вне repo | Fallback Windows / ASCII-пути |

Пути в `config.yaml` задаются **относительно каталога config** (`back/project/`):

```yaml
faiss:
  index_path: data/faiss_index.bin
  chunks_path: data/chunks.json
  top_k: 8                      # после задачи 1.2 (было 1)
  confidence_threshold: 0.75    # cosine similarity после задачи 1.1
  min_delta: 0.002              # в коде Django НЕ используется
```

### 1.2. Откуда берутся чанки (важное ограничение)

**В репозитории нет скрипта**, который:

- парсит PDF/DOCX паспортов или ГОСТов;
- режет документы на чанки с overlap;
- добавляет `document_name` / `page_number`.

`build.py` **только** читает готовый `chunks.json` и строит FAISS.

**Фактическая происхождение данных** (по структуре JSON): автоматизированный или ручной **скrape/ETL карточек продуктов** с `https://www.turbo-don.ru/...`. Поля `product_url`, `metadata.url`, `metadata.section_title` это подтверждают.

**PyMuPDF, EasyOCR, python-docx** в проекте есть, но в модуле `pdf_order_analysis.py` — для **сценария заказа**, не для KB.

### 1.3. Схема чанка

Корень `chunks.json`:

```json
{
  "total_chunks": 682,
  "total_products": 51,
  "chunks": [ ... ]
}
```

Элемент массива `chunks`:

| Поле | Пример | Использование в RAG |
|------|--------|---------------------|
| `chunk_id` | `..._ufg_specs_2` | Dedup, отладка, контекст LLM |
| `product_url` | URL turbo-don.ru | Не в промпте напрямую |
| `product_title` | «Turbo Flow UFG-F…» | ProductDetector, промпт LLM |
| `chunk_type` | см. ниже | Фильтр `chunk_types_filter` |
| `content` | текст | **Единственное поле для эмбеддинга** |
| `metadata` | `{ type, url, section_title? }` | Не в промпт как цитата |

**Типы `chunk_type` (фактически):**

- `basic_info` — описание продукта
- `applications` — область применения
- `specifications` — таблица ТХ
- `features` — особенности / преимущества
- `section` — произвольная секция страницы (`metadata.section_title`)

**Отсутствуют (запланировано в RAG_REFACTOR_PLAN §4.1):** `document_name`, `page_number`, `doc_type` (`gost` | `passport` | `catalog`).

### 1.4. Пайплайн индексации (`build.py`)

Последовательность:

1. `SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")`
2. Загрузка `chunks.json` → список `texts = [c["content"] for c in chunks]`
3. `model.encode(texts, normalize_embeddings=True, convert_to_numpy=True).astype("float32")`
4. `faiss.IndexFlatIP(dim)` → `index.add(embeddings)`
5. `faiss.write_index(index, "faiss_index.bin")`

**Математика:** при L2-нормализованных векторах inner product = **косинусное сходство** ∈ `[-1, 1]`. Для семантически близких фрагментов типично `0.3…0.95`.

**Команда:**

```powershell
cd back/project/data
python build.py
```

### 1.5. Инвариант «индекс ↔ чанки»

```
chunks[i]["content"]  →  embedding[i]  →  FAISS row i
VectorStore.search → index idx  →  self.chunks[idx]
```

**Нарушение** (переставили/удалили чанки без пересборки индекса) → retrieval возвращает **чужой текст** при «нормальном» score.  
**Восстановление:** пересборка `build.py` + перезапуск Daphne.

### 1.6. Что **не** индексируется

- `product_title` (только `content`)
- `metadata`
- Внешние PDF/DOCX
- Диалоги пользователей (PostgreSQL `Message` — отдельно)

---

## 2. Runtime: компоненты RAG (`chatbot_core/`)

Продакшен-код: `back/chatbot/api/chatbot_core/`.  
Legacy-дубликат (консольный прототип): `back/project/chat.py`, `vector_store.py`, `llm_client.py` — **не вызывается Django**.

### 2.1. Карта модулей

| Модуль | Класс / функция | Ответственность |
|--------|-----------------|-----------------|
| `embeddings.py` | `EmbeddingModel` | encode / encode_batch, normalize |
| `vector_store.py` | `VectorStore` | FAISS search → список dict с score |
| `product_detector.py` | `ProductDetector` | продукт из вопроса; чанки по названию |
| `question_classifier.py` | `QuestionClassifier` | тип вопроса → параметры поиска |
| `chatbot.py` | `AdvancedChatbot`, `smart_search`, `adjust_search_parameters` | оркестрация |
| `llm_client.py` | `LLMClient` | контекст + вызов LM Studio + постобработка |
| `__init__.py` | re-export | `from .chatbot_core import AdvancedChatbot` |

### 2.2. EmbeddingModel

```python
# embeddings.py
self.model.encode(text, normalize_embeddings=True)  # → float32, L2-norm ≈ 1
```

Одна модель для: запроса, шаблонов классификатора, названий продуктов, всех чанков при build. **Смена model_name** требует пересборки индекса и рестарта.

### 2.3. VectorStore.search (после задачи 1.1)

```python
similarities, indices = self.index.search(query_embedding, top_k)
score = float(similarity)  # чем выше — тем релевантнее
```

Возвращает dict: `chunk_id`, `chunk_type`, `product_title`, `content`, `metadata`, `score`.

Опциональный `product_filter` — substring в `product_title` (в `smart_search` сейчас не используется).

**Исторический баг (исправлен):** `score = 1 - dist/2` трактовал IP как distance и **инвертировал** ранжирование; порог 0.75 фактически соответствовал cosine ≈ 0.5.

### 2.4. QuestionClassifier

**Вход:** строка вопроса.  
**Механизм:** cosine similarity вопроса к ~40 **шаблонным фразам** (5 типов × 4–10 фраз).  
**Порог активации типа:** 0.25.  
**Fallback:** `keyword_classify()` — regex (`какой`, `расход`, `давление`…) → `attribute`; иначе default `description`.

**Выход:**

```python
{
  "is_attribute": bool,
  "is_description": bool,
  "is_comparison": bool,
  "is_selection": bool,
  "is_operation": bool,
  "confidence": float,
  "main_type": str,
}
```

Классификатор **не** выбирает чанки — только **настраивает** `top_k`, `threshold`, `chunk_types_filter`.

### 2.5. adjust_search_parameters

| Условие | top_k | threshold | chunk_types_filter |
|---------|-------|-----------|-------------------|
| `is_attribute` | 25 | 0.0 | specifications, basic_info, applications |
| `is_description` | 15 | 0.4 | basic_info, applications |
| `is_comparison` | 20 | 0.3 | specifications, basic_info |
| иначе | `max(config.top_k, 5)` → **8** | `confidence_threshold` **0.75** | `None` |

Для attribute порог **отключён** — LLM вызывается даже при низком score.

### 2.6. ProductDetector

**detect_product_from_question(question):**

1. Уникальные `product_title` из всех чанков (нормализация: без скобок, ≤7 слов).
2. Cosine вопрос ↔ каждое название (кэш эмбеддингов продуктов).
3. Порог **0.4** → `(product_name, score)` или `(None, score)`.

**search_chunks_by_product(product, top_k=15):**

- Линейный scan `store.chunks`, substring match по `product_title`.
- **Искусственный score: 0.8 / 0.9** — **дефект, задача 1.5 не выполнена**.
- Может доминировать над реальным vector score при merge в `smart_search`.

### 2.7. smart_search

```
IF product detected (score > 0.4):
    product_chunks = search_chunks_by_product(15)   # score 0.8/0.9
    vector_results = VectorStore.search(top_k)
    merge → dedup by chunk_id → sort by score desc → [:top_k]
ELSE:
    VectorStore.search(top_k)
```

**Нет:** reranking, BM25, cross-encoder, `min_delta`.

### 2.8. generate_response — decision graph

```
config is None? → "чатбот недоступен"
is_greeting?    → шаблонный ответ (без RAG, без LLM)
classify question
adjust_search_parameters
encode question
smart_search
filter by chunk_types_filter (см. §2.9)
results empty?  → fallback (без LLM)
NOT attribute AND best.score < threshold? → fallback (без LLM)
LLMClient.generate(chunks, question, question_type)
empty answer?   → fallback
```

`self.last_chunks` — последний набор чанков (отладка, не в API).

### 2.9. Фильтрация chunk_types_filter (дефект, задача 1.3)

```python
if filter and results:
    filtered = [r for r in results if r.chunk_type in filter]
    if filtered:
        results = filtered
```

| Ситуация | Поведение |
|----------|-----------|
| После фильтра ≥1 чанк | Используются только отфильтрованные |
| После фильтра 0 чанков | **Откат к полному списку** (фильтр игнорируется) |
| После фильтра 1 чанк | LLM получает **один** чанк — риск неполного ответа |

**План 1.3:** если `< 2` чанков — отключить фильтр явно + log.

### 2.9. LLMClient

**Endpoint:** LM Studio, OpenAI-compatible (`openai` SDK, `api_key="lm-studio"`).  
**Конфиг:** `base_url`, `model`, `temperature=0.2`, `max_tokens=512`, `timeout=90`.

**build_context(chunks):** блоки с `chunk_id`, score, product_title, chunk_type, content.  
**Нет цитирования** `[Документ: …, стр. X]` — задача 1.4 / FR-11.

**Промпт:** запрет CoT, «chunk», «context»; для attribute — акцент на параметры с единицами.

**Постобработка:**

- `_strip_chain_of_thought()` — `<think>`, «Thinking Process»
- `_post_process_answer()` — dedup строк

Retry: 2 повтора при timeout.

---

## 3. Интеграция с Django и frontend

### 3.1. Точка входа API

```
POST /api/chats/<chat_id>/messages/
View: MessageViewSet.create()  — back/chatbot/api/views.py
Serializer: MessageSerializer — id, content, is_user, created_at, image_url, attachment_url
```

### 3.2. Когда вызывается RAG

```python
is_start_like = (current_state == 'start') or state_data.get('is_final')

if is_start_like:
    if looks_like_order_specs_request(text):
        → order_specs_text pipeline  # НЕ RAG
    else:
        bot = get_chatbot()
        bot_response = bot.generate_response(question)
```

Дополнительно RAG вызывается в ветке `else` (не locked, не hint selection) — строки ~2037–2040 `views.py`.

### 3.3. Синглтон get_chatbot()

```python
# views.py
_chatbot_instance = None

def get_chatbot():
    if _chatbot_instance is None:
        _chatbot_instance = AdvancedChatbot(config_path)
    return _chatbot_instance
```

**Lazy init** — тяжёлые libs при первом RAG-запросе.  
**Нет** `reload()`, `healthcheck()` — запланировано в RAG_REFACTOR_PLAN §3.1.  
**Отдельно:** `get_order_specs_llm()` — только LLM без FAISS.

### 3.4. Windows / Unicode

`_faiss_readable_paths()` копирует index + chunks в `C:\temp\chatbot\_rag_mirror\` если путь содержит кириллицу. Workspace `C:\Users\...\мусор\проект2 (чатбот)` **триггерит** это поведение.

### 3.5. Frontend

**Файлы:** `front/chatbot/src/components/ChatWidget.js`, `api.js`, `config.js`.

**RAG-запрос (addMessage):**

```javascript
await createMessage(chatId, {
  content: text,
  hint_state: hintState.currentState,
  is_hint_selection: false,
  hint_locked: hintLocked,
});
// → POST http://127.0.0.1:8002/api/chats/<id>/messages/
```

**Ответ:** `response.data.messages` — user + bot; bot `content` → plain text в UI.  
Карточки оборудования / слайдер — **не RAG**, а `order_final` + `fetchSearchEquipment` → `:8010`.

### 3.6. Полный trace одного RAG-запроса

1. Пользователь: «Какой диапазон давления у UFG-F?», state=`start`.
2. `ChatWidget.addMessage` → POST messages.
3. `MessageViewSet.create` → save user Message.
4. `looks_like_order_specs_request` → False.
5. `get_chatbot()` → init при первом вызове (config, FAISS, ST model, LLM).
6. `generate_response`:
   - не greeting;
   - classify → likely `attribute`;
   - top_k=25, threshold=0, filter specs/basic/applications;
   - ProductDetector может найти «Turbo Flow UFG-F»;
   - smart_search → merge product + vector chunks;
   - filter by chunk_type;
   - threshold skip (attribute);
   - LLM generate.
7. Save bot Message.
8. Response JSON → frontend render text.

---

## 4. Конфигурация, зависимости, окружение

### 4.1. Python-зависимости (RAG)

```
openai==1.58.1
sentence-transformers==3.3.1
faiss-cpu==1.9.0.post1
PyYAML
numpy
```

### 4.2. Инфраструктура (из .cursorrules / settings)

| Сервис | Адрес | Роль |
|--------|-------|------|
| Django (Daphne) | `:8002` | API |
| React | `:3001` | UI |
| LM Studio | `192.168.5.53:1234/v1` | LLM generation |
| Внешние сервисы | `192.168.5.49:8010` | search-equipment, price, заявки (**не RAG**) |
| PostgreSQL | на сервере | prod БД; локально может быть sqlite3 |

Деплой backend: `deploy_backend.py` (может отсутствовать в repo). **Не запускать prod backend локально** по правилам проекта.

### 4.3. Параметры с семантикой «после рефакторинга 1.1–1.2»

| Параметр | Значение | Смысл |
|----------|----------|-------|
| score | cosine similarity | 1.0 = идентичное направление в embedding space |
| confidence_threshold | 0.75 | для non-attribute: LLM только если best score ≥ 0.75 |
| top_k default | 8 | сколько кандидатов из FAISS (до фильтров) |

**Побочный эффект 1.1:** порог 0.75 стал **строже**, чем при старой формуле (раньше пропускало ~0.5 cosine). Возможен рост доли fallback.

---

## 5. Соседние контуры (кратко, для контекста DeepSeek)

### 5.1. PDF/DOCX подбор

`pdf_order_analysis.py`: PyMuPDF → EasyOCR → LLM JSON → `Chat.order_specs_draft` → подтверждение → frontend GET `:8010/search-equipment`.

### 5.2. Текстовый подбор

`order_specs_text.py`: intent regex → LLM + heuristics → тот же draft JSON.

### 5.3. FSM подсказок

`hints_tree.py` (~61 состояние): продажи, поверка, расходомеры, цена, СПУ, бытовые счётчики. RAG **не участвует** в locked-сценариях.

---

## 6. Известные проблемы и backlog

### 6.1. Статус RAG_REFACTOR_PLAN

| Задача | Описание | Статус |
|--------|----------|--------|
| 1.1 | Формула score | ✅ |
| 1.2 | top_k 8, min 5 | ✅ |
| 1.3 | Fallback chunk_types_filter | ❌ |
| 1.4 | Цитирование источников FR-11 | ❌ |
| 1.5 | ProductDetector score 0.8/0.9 | ❌ |
| 2.x | BM25 hybrid search | ❌ |
| 3.x | RagService, SOLID | ❌ |
| 4.x | Метаданные документов, versioning KB | ❌ |
| 5.x | Тесты, метрики | ❌ |

### 6.2. Структурные ограничения (не баги, а архитектура)

1. **KB = каталог сайта**, не нормативная библиотека → вопросы «какой ГОST регламентирует влажность» могут не находить первоисточник.
2. **Нет ETL в repo** → воспроизводимость KB под вопросом.
3. **Singleton без reload** → смена config/index требует рестарта Daphne.
4. **Один embedding field** — title и metadata не участвуют в retrieval.
5. **min_delta** в yaml — мёртвый параметр.
6. **ProductDetector merge** искажает ranking.
7. **Нет observability** — нет логов score/top_k/chunks в БД, нет `/api/rag/stats`.
8. **Нет тестов** `test_rag_pipeline.py`.

### 6.3. Failure modes

| Симптом | Вероятная причина |
|---------|------------------|
| Всегда fallback | strict threshold 0.75; пустой/устаревший index |
| Неверные факты | chunk↔index mismatch; один чанк после filter |
| Медленный первый ответ | cold start: ST + FAISS + torch |
| FAISS FileNotFound | index не собран; кириллица в пути без mirror |
| LLM timeout | LM Studio недоступна; max_tokens=512 мал |
| «Подбор» вместо Q&A | `looks_like_order_specs_request` перехватил |

---

## 7. Целевая модель (куда ведёт RAG_REFACTOR_PLAN)

Для ориентации DeepSeek — **желаемое**, не текущее:

```
Documents (GOST, passport, catalog, site)
    → ETL + chunking + rich metadata
    → chunks.json (versioned)
    → FAISS + BM25 (HybridRetriever)
    → RagService.answer()
        → classify → hybrid search → threshold → cite-aware LLM
    → answer with [Document, page]
    → metrics / tests / healthcheck
```

Критерии готовности из плана: FR-11/AC-04 (цитаты), CSAT > 85%, TTR < 30s, покрытие тестами 70% ключевых путей.

---

## 8. Справочник: ключевые файлы и функции

```
back/project/
  config.yaml
  data/chunks.json
  data/build.py
  data/faiss_index.bin          # local, not in git

back/chatbot/api/
  views.py                      get_chatbot(), MessageViewSet.create()
  chatbot_core/
    chatbot.py                    AdvancedChatbot, smart_search, adjust_search_parameters
    vector_store.py               VectorStore.search
    embeddings.py                 EmbeddingModel
    product_detector.py           ProductDetector
    question_classifier.py        QuestionClassifier
    llm_client.py                 LLMClient

front/chatbot/src/
  components/ChatWidget.js        addMessage, UI
  api.js                          createMessage
  config.js                       API_BASE_URL :8002
```

---

## 9. Prompt для DeepSeek (скопировать при анализе)

```
Ты — Senior RAG Engineer. Прочитай RAG_PIPELINE.md и связанные файлы
(DEEPSEEK_PROJECT_ANALYSIS.md, RAG_REFACTOR_PLAN.md, TZ_chatbot_Turbo_Don.md).

Контекст: чатбот Turbo-Don, Django + React, LM Studio, FAISS, chunks с turbo-don.ru.
Уже сделано: исправлен score (cosine IP), top_k=8. Не сделано: 1.3–1.5, hybrid search, citations, KB ETL.

Задачи анализа:
1. Оцени архитектуру RAG: слабые места retrieval, ranking, KB coverage.
2. Сопоставь с FR-11 (цитирование) и AC-04 — gap analysis.
3. Приоритизируй RAG_REFACTOR_PLAN §1.3–1.5 с учётом строгого threshold 0.75.
4. Предложи дизайн ETL для ГОСТ/паспортов + versioning без переписывания всего.
5. Укажи минимальный набор интеграционных тестов (3–5 кейсов с ожидаемым поведением).
6. Оцени риск ProductDetector score 0.9 vs vector score после fix 1.1.

Формат ответа: executive summary, таблица рисков, рекомендуемый порядок работ, конкретные правки по файлам.
```

---

## 10. История изменений документа

| Дата | Изменение |
|------|-----------|
| 2026-05-22 | Первая версия для DeepSeek; отражает задачи 1.1–1.2 |

---

*Конец документа.*

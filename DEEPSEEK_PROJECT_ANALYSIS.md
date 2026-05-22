# Контекст проекта для анализа ИИ (DeepSeek)

Документ подготовлен для передачи другому ИИ на глубокий анализ проекта. Основной фокус: backend, RAG, LLM-интеграции, сценарии чатбота и связи с frontend.  
Проект: чатбот Turbo-don для консультаций, подбора оборудования, оформления заявок и интеграции с внешними сервисами.

> Важно: в проекте есть локальные IP-адреса, dev-конфиги и hardcoded `SECRET_KEY` в `settings.py`. Если документ отправляется во внешний сервис, нужно учитывать риск утечки внутренней инфраструктуры.

---

## 1. Высокоуровневое назначение проекта

Проект реализует web-чатбота для сайта/внутреннего интерфейса Turbo-don.

Основные функции:

1. Обычный Q&A по оборудованию через RAG:
   - пользователь задаёт вопрос;
   - backend ищет релевантные фрагменты в FAISS-индексе;
   - контекст отправляется в LM Studio через OpenAI-compatible API;
   - модель отвечает по-русски на основе найденных чанков.

2. Подбор расходомеров:
   - пользователь может выбрать сценарий через подсказки;
   - можно загрузить PDF/DOCX с параметрами;
   - backend извлекает текст через PyMuPDF / EasyOCR / python-docx;
   - LM Studio + эвристики извлекают JSON спецификации;
   - пользователь подтверждает таблицу параметров;
   - frontend вызывает внешний сервис `search-equipment` на `:8010`;
   - найденное оборудование показывается слайдером.

3. Текстовый подбор расходомеров:
   - пользователь в свободной форме пишет параметры расходомера;
   - backend распознаёт intent;
   - LLM + regex-эвристики извлекают такой же JSON, как из PDF;
   - если не хватает полей, бот просит уточнить недостающие параметры одним сообщением;
   - если всё есть, показывает таблицу подтверждения.

4. Получение цены:
   - после выбора оборудования можно нажать `Получить цену`;
   - frontend собирает body для `estimate-price`;
   - для отдельных приборов цена недоступна на frontend-уровне;
   - для остальных запускается серверный сценарий: телефон -> email -> код -> запрос цены.

5. Заявки:
   - поверочные установки;
   - СПУ газ;
   - бытовые счётчики газа;
   - заявки отправляются во внешние сервисы на `:8010`.

6. Администрирование чатов:
   - создание чата;
   - список сообщений;
   - архивирование;
   - финализация;
   - генерация заголовка через LLM/RAG.

---

## 2. Структура проекта

Корень:

```text
проект2 (чатбот)/
  back/
    chatbot/                 # Django backend
    project/                 # RAG-конфиг, chunks, build index, старый console prototype
    templates/static/        # статика оборудования, картинки
    copy_config.py           # копирование config.yaml в C:\temp\chatbot
  front/
    chatbot/                 # React frontend
```

Ключевые backend-пути:

```text
back/chatbot/
  manage.py
  requirements.txt
  run_daphne.ps1
  chatbot/
    settings.py
    urls.py
    asgi.py
    wsgi.py
  api/
    models.py
    serializers.py
    urls.py
    views.py
    hints_tree.py
    order_specs_helpers.py
    order_specs_text.py
    pdf_order_analysis.py
    search_equipment.py
    gas_spu_wizard.py
    verification_client.py
    submit_household_gas.py
    submit_spu_application.py
    submit_verification_liquid.py
    email_service.py
    email_config.py
    chatbot_core/
      chatbot.py
      embeddings.py
      vector_store.py
      llm_client.py
      product_detector.py
      question_classifier.py
```

Ключевые RAG/данные:

```text
back/project/
  config.yaml
  data/
    chunks.json
    build.py
    faiss_index.bin        # должен быть рядом после сборки, может отсутствовать в git
  chat.py                  # старый/консольный аналог RAG
  embeddings.py
  vector_store.py
  llm_client.py
```

Ключевые frontend-пути:

```text
front/chatbot/
  package.json
  .env.development
  src/
    api.js
    config.js
    App.js
    App.css
    components/
      ChatWidget.js
      OrderSpecsTextClarify.js
      orderSpecsConfirmTable.js
      gasSpuResultCard.js
      GrandGasMetersPriceBlock.js
    utils/
      searchEquipment.js
```

---

## 3. Технологический стек

Backend:

- Django / DRF.
- Daphne / ASGI, фактический dev-порт: `8002`.
- SQLite в локальном `settings.py`, хотя рабочая память пользователя говорит, что настоящая база на сервере PostgreSQL. В коде сейчас `sqlite3`, это важно проверить при деплое.
- `openai==1.58.1` для LM Studio OpenAI-compatible API.
- `sentence-transformers==3.3.1`.
- `faiss-cpu==1.9.0.post1`.
- `PyMuPDF`, `easyocr`, `python-docx` для обработки PDF/DOCX.
- `requests`, `urllib` для внешних HTTP-интеграций.

Frontend:

- React `19.2.3`.
- CRA `react-scripts`.
- Axios.
- Dev-порт обычно `3001`.

Внешние сервисы:

- Django API: `http://192.168.5.49:8002/api` в `.env.development`.
- 1C/подбор/прайс/ТКП сервисы: `http://192.168.5.49:8010/...`.
- LM Studio: `http://192.168.5.53:1234/v1/`.
- Модель LM Studio: `yandexgpt-5-lite-8b-instruct`.

---

## 4. Запуск и окружение

Backend:

```powershell
cd back/chatbot
py -3 -m daphne -b 0.0.0.0 -p 8002 chatbot.asgi:application
```

Есть скрипт:

```text
back/chatbot/run_daphne.ps1
```

Он запускает Daphne на `0.0.0.0:8002`.

Frontend:

```powershell
cd front/chatbot
$env:PORT='3001'
$env:HOST='0.0.0.0'
$env:DANGEROUSLY_DISABLE_HOST_CHECK='true'
npm start
```

`.env.development`:

```text
REACT_APP_API_URL=http://192.168.5.49:8002
REACT_APP_SEARCH_EQUIPMENT_URL=http://192.168.5.49:8010/api/search-equipment
REACT_APP_ESTIMATE_PRICE_URL=http://192.168.5.49:8010/api/estimate-price
REACT_APP_TKP_ACCESSORIES_URL=http://192.168.5.49:8010/api/tkp-accessories
REACT_APP_TKP_PDF_URL=http://192.168.5.49:8010/api/tkp-pdf
```

Особое правило эксплуатации от владельца проекта:

- не пытаться запускать настоящий backend локально как production;
- настоящий backend находится на сервере;
- для деплоя backend используется `deploy_backend.py`, хотя в текущем рабочем дереве файл не найден;
- настоящая БД на сервере PostgreSQL.

---

## 5. Django backend: общая архитектура

### 5.1 Основные модели

Файл: `back/chatbot/api/models.py`

`Chat`:

- `title`;
- `ip_address`;
- `created_at`;
- `is_archived`;
- `order_specs_draft`: JSONField, хранит черновик спецификации расходомера;
- `order_specs_pending_field`: текущее поле, которое надо уточнить;
- `price_quote_draft`: временный JSON для сценария цены.

Методы:

- `should_be_archived`: старше 10 дней;
- `message_count`;
- `archive_old_chats`;
- `delete_empty_chats`.

`Message`:

- `chat`;
- `content`;
- `image`;
- `attachment`;
- `is_user`;
- `created_at`;
- `has_image`;
- `has_attachment`.

### 5.2 Сериализация

Файл: `back/chatbot/api/serializers.py`

`MessageSerializer`:

- отдаёт `image_url`;
- отдаёт `attachment_url`;
- `image` и `attachment` write-only.

`ChatSerializer`:

- включает сообщения;
- message_count;
- should_be_archived.

### 5.3 URL

Файл: `back/chatbot/chatbot/urls.py`

```text
/admin/
/api/
```

Файл: `back/chatbot/api/urls.py`

```text
/api/chats/
/api/chats/<chat_id>/messages/
/api/hints/
/api/validate-email/
/api/test-email/
/api/templates/purs-questionnaire/
/api/equipment-media/<path>
```

### 5.4 Views

Файл: `back/chatbot/api/views.py`

Главные классы:

- `ChatViewSet`;
- `MessageViewSet`;
- `HintsView`;
- `EmailValidationView`;
- `TestEmailView`.

Главные функции:

- `get_chatbot()`: лениво инициализирует RAG-бота `AdvancedChatbot`;
- `get_order_specs_llm()`: лёгкий LLM-клиент без загрузки FAISS/embeddings, нужен для PDF/text specs;
- `_handle_order_specs_text_message()`: свободный текст -> specs JSON -> clarify/table;
- `_transition_to_order_specs_confirm()`: сохранить черновик и отдать preview таблицы;
- `_safe_print_order_specs_final()`: логирование итоговой спецификации;
- `reload_chatbot()`: сбрасывает глобальный RAG singleton;
- `generate_chat_title()`: генерация названия чата через LLM/RAG;
- набор `_parse_*` helper-ов для JSON из frontend.

`MessageViewSet.create()` — центральный обработчик всей бизнес-логики:

1. сохраняет пользовательское сообщение;
2. читает `hint_state`, `is_hint_selection`, `hint_locked`;
3. ветвится по сценарию:
   - подсказки;
   - стартовое свободное сообщение;
   - заблокированный сценарий;
   - PDF/DOCX спецификация;
   - текстовая спецификация;
   - цена;
   - верификация;
   - заявки;
   - обычный RAG Q&A;
4. создаёт bot message;
5. отдаёт расширенный payload frontend-у:
   - `messages`;
   - `hint_state`;
   - `order_specs_json`;
   - `order_specs_preview`;
   - `order_specs_clarify_preview`;
   - `order_specs_llm_response`;
   - `order_specs_ocr_text`;
   - `verification_passed`;
   - payload-и заявок и карточек.

---

## 6. Система подсказок / state machine

Файл: `back/chatbot/api/hints_tree.py`

`HINTS_TREE` — большое дерево состояний. Каждый узел обычно содержит:

- `id`;
- `bot_message`;
- `hints`;
- `expects_input`;
- `is_final`;
- `show_back`;
- `next_state`;
- иногда `hints_only`.

Старт:

```text
start
  -> Подбор оборудования
  -> Продажа оборудования
  -> Поверка
  -> Пуско-наладочные работы
  -> Обратная связь
  -> Отклик на вакансию
  -> Другое
```

Подбор:

```text
equipment_pick
  -> Расходомеры
  -> Поверочные установки
  -> Бытовые счетчики газа
  -> Плотномеры
  -> Датчики давления
```

Расходомеры:

```text
order_pdf_request
  -> order_specs_clarify
  -> order_specs_text_clarify
  -> order_specs_confirm
  -> order_final
```

Цена:

```text
order_final
  -> equipment_price_phone
  -> equipment_price_email
  -> equipment_price_verify_code
  -> order_final
```

Важно:

- обычный RAG Q&A работает в `start` или в `is_final` состояниях, если сообщение не распознано как текстовый подбор расходомера;
- когда сценарий `hint_locked=True`, текст пользователя обрабатывается строго по текущему состоянию.

---

## 7. RAG backend: актуальная реализация

Актуальная Django-интеграция находится в:

```text
back/chatbot/api/chatbot_core/
```

Старый/консольный прототип находится в:

```text
back/project/
```

Фактически Django использует классы из `back/chatbot/api/chatbot_core`, но config и данные берёт из `back/project`.

### 7.1 Инициализация RAG

В `views.py`:

```python
_chatbot_instance = None

def get_chatbot():
    global _chatbot_instance
    if _chatbot_instance is None:
        from .chatbot_core import AdvancedChatbot
        project_root = .../back/project
        config_path = .../back/project/config.yaml
        if not exists:
            config_path = r'C:\temp\chatbot\config.yaml'
        _chatbot_instance = AdvancedChatbot(config_path)
    return _chatbot_instance
```

Особенности:

- heavy dependencies (`torch`, FAISS, sentence-transformers) импортируются лениво;
- `GET /api/hints/` не должен грузить RAG;
- если поменять `config.yaml`, нужно перезапустить Daphne или вызвать `reload_chatbot()`, потому что singleton кэширует клиента и config.

### 7.2 Конфиг RAG

Файл: `back/project/config.yaml`

```yaml
embeddings:
  model_name: paraphrase-multilingual-MiniLM-L12-v2

faiss:
  index_path: data/faiss_index.bin
  chunks_path: data/chunks.json
  top_k: 1
  confidence_threshold: 0.75
  min_delta: 0.002

llm:
  base_url: http://192.168.5.53:1234/v1/
  model: yandexgpt-5-lite-8b-instruct
  temperature: 0.2
  max_tokens: 512
  timeout: 90

messages:
  fallback: >
    Не удалось найти информации по вашему запросу.
    Для подробной информации свяжитесь с нашей организацией.
```

`min_delta` в текущей Django-реализации не видно как активно используемый параметр. Нужно проверить, был ли он запланирован для reranking/отсечения близких результатов.

### 7.3 Данные RAG

Файл: `back/project/data/chunks.json`

В начале файла:

```json
{
  "total_chunks": 682,
  "total_products": 51,
  "chunks": [...]
}
```

Каждый chunk содержит примерно:

```json
{
  "chunk_id": "...",
  "product_url": "https://www.turbo-don.ru/...",
  "product_title": "Ультразвуковой расходомер-счетчик газа Turbo Flow UFG-F",
  "chunk_type": "basic_info | applications | specifications | section | ...",
  "content": "текст чанка",
  "metadata": {
    "type": "...",
    "url": "...",
    "section_title": "..."
  }
}
```

Типы чанков, которые явно используются:

- `basic_info`;
- `applications`;
- `specifications`;
- `section`;
- возможно другие, надо статистически пройти весь `chunks.json`.

### 7.4 Сборка FAISS-индекса

Файл: `back/project/data/build.py`

Pipeline:

1. загрузить `chunks.json`;
2. взять `content` каждого чанка;
3. закодировать моделью `paraphrase-multilingual-MiniLM-L12-v2`;
4. `normalize_embeddings=True`;
5. `convert_to_numpy=True`;
6. привести к `float32`;
7. создать `faiss.IndexFlatIP(dim)`;
8. добавить embeddings;
9. сохранить `faiss_index.bin`.

Команда:

```powershell
cd back/project/data
python build.py
```

Важно:

- индекс строится только по `content`, не по `product_title`;
- `IndexFlatIP` при нормализованных embeddings фактически даёт cosine similarity;
- в `VectorStore.search()` score считается как `1 - dist / 2`, что выглядит подозрительно для `IndexFlatIP`: FAISS возвращает inner product similarity, а не distance. Для cosine/IP значение обычно чем больше, тем лучше, диапазон примерно `[-1, 1]`. Формула `1 - dist/2` инвертирует смысл: при `dist=0.9` score = 0.55, при `dist=0.2` score = 0.9. Это может ломать threshold и сортировку. Это один из главных пунктов для анализа DeepSeek.

### 7.5 Windows/Unicode workaround

Файл: `back/chatbot/api/chatbot_core/chatbot.py`

Функция `_faiss_readable_paths()`:

- пытается проверить, ASCII ли пути к `faiss_index.bin` и `chunks.json`;
- если путь содержит кириллицу/Unicode, копирует файлы в:

```text
C:\temp\chatbot\_rag_mirror\
  faiss_index.bin
  chunks.json
```

Причина: FAISS C++ на Windows часто плохо читает файлы по Unicode-пути.

Это критично, потому что workspace находится в пути с кириллицей:

```text
C:\Users\uaa\Desktop\мусор\проект2 (чатбот)
```

### 7.6 Embeddings

Файл: `back/chatbot/api/chatbot_core/embeddings.py`

`EmbeddingModel`:

- инициализирует `SentenceTransformer(model_name)`;
- `encode(text)`:
  - если строка, оборачивает в список;
  - вызывает `model.encode(..., normalize_embeddings=True)`;
  - возвращает первый embedding для одиночного текста;
- `encode_batch(texts)`:
  - возвращает пустой `np.array([])`, если нет текстов;
  - иначе batch encode.

Модель:

```text
paraphrase-multilingual-MiniLM-L12-v2
```

### 7.7 VectorStore

Файл: `back/chatbot/api/chatbot_core/vector_store.py`

`VectorStore.__init__(index_path, chunks_path)`:

- `faiss.read_index(index_path)`;
- читает `chunks.json`;
- проверяет `data["chunks"]` как list.

`VectorStore.search(query_embedding, top_k, product_filter=None)`:

- приводит 1D embedding к `(1, dim)`;
- вызывает `self.index.search(query_embedding, top_k)`;
- получает `distances`, `indices`;
- для каждого idx:
  - берёт chunk;
  - если `product_filter`, фильтрует по `product_title`;
  - считает `confidence = 1 - float(dist) / 2`;
  - возвращает словарь:
    - `chunk_id`;
    - `chunk_type`;
    - `product_title`;
    - `content`;
    - `metadata`;
    - `score`.

Потенциальная проблема:

- при `IndexFlatIP` переменная `dist` на самом деле similarity / inner product;
- формула score, вероятно, некорректна;
- `results` сохраняются в порядке FAISS, но затем в `smart_search` после объединения с product chunks сортируются по `score`, который может быть неверным.

### 7.8 ProductDetector

Файл: `back/chatbot/api/chatbot_core/product_detector.py`

Цель: определить продукт из вопроса.

`extract_product_names()`:

- проходит по `store.chunks`;
- берёт `product_title`;
- убирает текст в скобках;
- обрезает до первых 7 слов;
- фильтрует короткие названия;
- кэширует список.

`detect_product_from_question(question)`:

- кодирует вопрос embedding-моделью;
- кодирует все product names, кэшируя embeddings;
- считает cosine вручную через `np.dot(normalized vectors)`;
- если лучший score > 0.4, возвращает product.

`search_chunks_by_product(product_name, top_k=10)`:

- ищет подстрочное совпадение product_name / варианты с `-` и пробелами в `chunk.product_title`;
- назначает score:
  - 0.9 при точном/сильном совпадении;
  - 0.8 базово;
- сортирует по score;
- возвращает top_k.

Потенциальные проблемы:

- обрезание `product_title` до 7 слов может вредить длинным техническим названиям;
- поиск по продукту не учитывает вопрос/параметр, просто возвращает первые чанки продукта;
- score 0.8/0.9 может доминировать над векторным поиском;
- нет BM25/keyword reranking.

### 7.9 QuestionClassifier

Файл: `back/chatbot/api/chatbot_core/question_classifier.py`

Классы вопросов:

- `attribute`;
- `description`;
- `comparison`;
- `selection`;
- `operation`.

Механика:

1. заранее кодирует шаблоны вопросов;
2. кодирует вопрос;
3. считает cosine similarity с шаблонами;
4. выбирает `main_type`;
5. threshold = `0.25`;
6. выставляет флаги:
   - `is_attribute`;
   - `is_description`;
   - `is_comparison`;
   - `is_selection`;
   - `is_operation`.

Fallback `keyword_classify()`:

- если есть слова `диаметр`, `давление`, `расход`, `погрешность`, `температура`, `диапазон`, `размер` и т.д. -> attribute;
- `что такое`, `описание`, `назначение` -> description;
- иначе description.

### 7.10 adjust_search_parameters()

Файл: `back/chatbot/api/chatbot_core/chatbot.py`

В зависимости от типа вопроса:

Attribute:

```python
top_k = 25
threshold = 0.0
chunk_types_filter = ["specifications", "basic_info", "applications"]
search_strategy = "aggressive"
```

Description:

```python
top_k = 15
threshold = 0.4
chunk_types_filter = ["basic_info", "applications"]
```

Comparison:

```python
top_k = 20
threshold = 0.3
chunk_types_filter = ["specifications", "basic_info"]
```

Other:

```python
top_k = config.faiss.top_k
threshold = config.faiss.confidence_threshold
chunk_types_filter = None
```

Важно:

- в `config.yaml` `top_k=1`, но для большинства осмысленных типов вопроса оно переопределяется;
- для attribute порог отключён (`0.0`);
- для description порог `0.4`.

### 7.11 smart_search()

Файл: `back/chatbot/api/chatbot_core/chatbot.py`

Алгоритм:

1. `product_detector.detect_product_from_question(question)`.
2. Если product найден и score > 0.4:
   - получить `product_chunks = search_chunks_by_product(product, top_k=15)`;
   - выполнить обычный vector search;
   - объединить `product_chunks + vector_results`;
   - убрать дубликаты по `chunk_id`;
   - отсортировать по `score`;
   - вернуть top_k.
3. Иначе:
   - обычный `store.search(query_embedding, top_k)`.

Риск:

- product chunks имеют искусственный score 0.8/0.9;
- vector chunks имеют score по спорной формуле;
- сортировка может быть невалидной;
- если product detection ошибся, RAG сильно смещается в неправильный продукт.

### 7.12 AdvancedChatbot.generate_response()

Файл: `back/chatbot/api/chatbot_core/chatbot.py`

Pipeline:

```text
question
  -> greeting detection
  -> classify(question)
  -> adjust_search_parameters()
  -> embedder.encode(question)
  -> smart_search()
  -> filter by chunk_types_filter
  -> if no results: fallback
  -> if not attribute and best score < threshold: fallback
  -> llm.generate(results, question, question_type)
  -> if empty: fallback
  -> return answer
```

Greeting detection:

- отдельный набор русских/английских приветствий;
- если приветствие, RAG/LLM не вызывается;
- возвращает случайный шаблонный ответ.

Fallback:

```text
Не удалось найти информации по вашему запросу.
Для подробной информации свяжитесь с нашей организацией.
```

### 7.13 LLMClient для RAG

Файл: `back/chatbot/api/chatbot_core/llm_client.py`

`_normalize_lm_base_url()`:

- гарантирует суффикс `/v1`;
- исправляет частую ошибку LM Studio base URL.

OpenAI client:

```python
OpenAI(
  base_url=base_url,
  api_key="lm-studio",
  timeout=timeout
)
```

`build_context(chunks)`:

Каждый chunk превращается в блок:

```text
[Чанк <id> (релевантность: 0.xx)]
Продукт: ...
Тип информации: ...

<content>
```

`generate(chunks, question, question_type)`:

- собирает context;
- определяет `main_product` по product_title из chunks;
- строит prompt:
  - "Ты — технический консультант";
  - "только фактами из контекста";
  - "если нет ответа — так и напиши";
  - запрет Thinking Process / Role / Task / chunk/context;
  - основной продукт;
  - контекст;
  - вопрос клиента.

Для attribute:

- просит только найденные значения параметров с единицами;
- если значения различаются, перечислить по модификациям;
- если параметра нет, сказать об этом.

Для прочего:

- ответ по существу;
- структурировать списком при необходимости.

`_call_llm()`:

- max_retries = 2;
- retry_delay = 2, затем умножается;
- логирует base_url/model/temperature/max_tokens/timeout;
- отправляет system + user;
- извлекает текст через `_extract_assistant_text`;
- чистит chain-of-thought через `_strip_chain_of_thought`;
- убирает дубликаты строк в `_post_process_answer`.

Анти-CoT:

- удаляет `<think>...</think>`;
- удаляет `<thinking>...</thinking>`;
- если есть `Thinking Process:`, пытается вырезать анализ и оставить русскоязычный ответ/параметры;
- фильтрует строки с `analyze`, `scan context`, `Role`, `Task`, `chunk`.

### 7.14 Основные риски RAG

1. Некорректная формула score для FAISS `IndexFlatIP`.
   - Индекс построен как inner product по нормализованным embeddings.
   - `VectorStore` считает `confidence = 1 - dist / 2`.
   - Для cosine/IP это может инвертировать релевантность.
   - Нужно проверить экспериментально.

2. `config.faiss.top_k = 1`.
   - Для unknown/other вопросов может давать один chunk.
   - Для description/attribute переопределяется, но не для всех.

3. Нет настоящего reranking.
   - Нет cross-encoder reranker.
   - Нет BM25 / keyword search.
   - Нет hybrid search.
   - ProductDetector может смещать выдачу.

4. ProductDetector кэширует embeddings по названиям.
   - При изменении chunks без restart singleton может иметь старые product list/embeddings.

5. Нет цитирования источников пользователю.
   - Prompt явно запрещает упоминать chunk/context.
   - Для диагностики может быть сложно понять источник ответа.

6. Context может быть слишком большим.
   - Для attribute top_k=25.
   - max_tokens всего 512.
   - Может приводить к неполному ответу.

7. `min_delta` не используется.

8. `chunks.json` и `faiss_index.bin` должны соответствовать друг другу по порядку.
   - Если chunks изменились, а индекс нет, результаты будут неправильными.

9. Нет явной проверки размерности embedding vs FAISS index.

10. Нет отдельного healthcheck для RAG:
    - доступность LM Studio;
    - наличие index/chunks;
    - количество чанков;
    - model loaded.

---

## 8. Старый/консольный RAG в `back/project`

`back/project/chat.py`, `embeddings.py`, `vector_store.py`, `llm_client.py` — похоже, исходная standalone версия RAG.

Она во многом дублирует Django `chatbot_core`:

- ProductDetector;
- QuestionClassifier;
- adjust_search_parameters;
- smart_search;
- LLMClient;
- VectorStore.

Отличия:

- `back/project/chat.py` запускает консольный чат через `main()`;
- имеет дополнительные функции типа `extract_parameter_keywords`;
- `back/project/vector_store.py` визуально имеет проблемный indent в сигнатуре `search()`:

```python
def search(
self,
query_embedding: np.ndarray,
...
)
```

Это может быть синтаксически невалидно или плохо отформатировано. Но Django, судя по коду, использует `back/chatbot/api/chatbot_core/vector_store.py`, где сигнатура нормальная.

Вывод:

- `back/project` сейчас одновременно:
  - источник config/data;
  - старый runnable prototype;
  - место сборки индекса.
- `back/chatbot/api/chatbot_core` — актуальная backend-интеграция.

---

## 9. PDF/DOCX -> specs JSON pipeline

Файл: `back/chatbot/api/pdf_order_analysis.py`

Назначение: извлечь технические параметры расходомера из PDF/DOCX.

### 9.1 OCR / text extraction

Константы:

```python
MAX_PDF_PAGES = 15
OCR_ZOOM = 1.25
MAX_OCR_CHARS = 120_000
MIN_PAGE_NATIVE_TEXT_CHARS = 40
MAX_LLM_INPUT_CHARS = 12_000
```

PDF:

- `pdf_to_text(file_path)`:
  - открывает PyMuPDF;
  - для каждой страницы до 15:
    - если есть текстовый слой >= 40 символов, берёт его;
    - иначе отправляет страницу в EasyOCR;
  - EasyOCR reader ленивый singleton;
  - возвращает `(text, source)` где source:
    - `pdf_text`;
    - `pdf_ocr`;
    - `pdf_mixed`.

DOCX:

- используется `python-docx` (детали выше/ниже в файле; нужно читать весь файл при рефакторинге).

EasyOCR:

- `api/apps.py` запускает background warmup при старте Django;
- можно отключить `ORDER_SPECS_SKIP_OCR_WARMUP=1`.

### 9.2 Схема спецификации

`SPEC_KEYS`:

```python
[
  "medium",
  "gas_type",
  "flowMin",
  "flowMax",
  "flow_unit",
  "pressureMin",
  "pressureMax",
  "pressure_unit",
  "tempMediumMin",
  "tempMediumMax",
  "tempAmbientMin",
  "tempAmbientMax",
  "temperature_unit",
  "accuracy",
  "diameter",
]
```

Legacy aliases:

```python
flow_min -> flowMin
flow_max -> flowMax
pressure_min -> pressureMin
pressure_max -> pressureMax
temperature_min -> tempMediumMin
temperature_max -> tempMediumMax
ambient_temp_min -> tempAmbientMin
ambient_temp_max -> tempAmbientMax
```

### 9.3 LLM extraction

`analyze_specs_with_llm(ocr_text, llm)`:

1. `extract_specs_heuristic(ocr_text)` — эвристики.
2. `_build_specs_extraction_prompt(ocr_text)`:
   - system: "Ты извлекаешь технические параметры расходомера";
   - ответ только JSON;
   - ключи строго `SPEC_KEYS`;
   - пример JSON.
3. Отправляет в LM Studio:
   - `temperature=0.1`;
   - `max_tokens=min(1024, llm.max_tokens)`;
   - timeout из llm.
4. Парсит JSON через `_parse_json_from_llm`.
5. Merges LLM data + heuristic.
6. `_postprocess_specs()`:
   - нормализует medium;
   - нормализует accuracy;
   - если accuracy missing, пытается вытащить из OCR.
7. Возвращает `(specs, raw_llm_text, llm_ms)`.

Если LLM падает:

- warning в лог;
- используются эвристики;
- если вообще ничего не извлечено, RuntimeError.

### 9.4 Связь с MessageViewSet

Когда пользователь находится в `order_pdf_request` и загрузил PDF/DOCX:

1. файл сохраняется как attachment;
2. `run_pdf_order_pipeline(abs_pdf, llm)`;
3. результат кладётся в `chat.order_specs_draft`;
4. `list_missing_fields(draft)`;
5. если missing:
   - state `order_specs_clarify`;
   - бот спрашивает одно поле;
6. если всё заполнено:
   - `_transition_to_order_specs_confirm`;
   - frontend получает `order_specs_preview`;
   - показывает таблицу.

---

## 10. Текстовый подбор расходомеров

Файл: `back/chatbot/api/order_specs_text.py`

Это новый важный сценарий: пользователь пишет параметры свободным текстом без PDF.

### 10.1 Intent detection

`looks_like_order_specs_request(text)`:

- проверяет regex на слова:
  - подобрать;
  - нужен;
  - ищу;
  - требуется;
  - расходомер;
  - оборудование;
  - DN/ДУ;
  - расход;
  - давление;
  - МПа/бар;
  - точность;
  - газ/жидкость.

Требования:

- длина >= 10;
- есть intent/equipment/числа/параметры;
- логика достаточно осторожная, чтобы не перехватывать обычные Q&A.

### 10.2 Быстрые regex-эвристики

`extract_specs_from_short_text(text)`:

- medium/gas_type:
  - природный газ;
  - газ;
  - жидкость.
- diameter:
  - DN/ДУ/диаметр.
- flow range:
  - `расход 3100-244000`;
  - если есть `м³/ч`, ставит `flow_unit = ст.м³/ч`.
- pressure range:
  - `давление 3,95-7,35`;
  - если `МПа`, `бар`, `кПа`, ставит unit.
- temperature:
  - рабочая среда;
  - окружающая среда.
- accuracy:
  - точность / класс точности.

### 10.3 LLM extraction для текста

`_llm_extract_text_specs(text, llm, base_draft)`:

- system: извлеки параметры расходомера из сообщения пользователя;
- ответ только JSON;
- ключи строго `SPEC_KEYS`;
- если значения нет в новом сообщении и нет в черновике — null;
- если пользователь указал новое значение — заменить черновик;
- не придумывать отсутствующие параметры.

`extract_order_specs_from_text(text, llm, base_draft)`:

1. `base = merge_draft(base_draft)`;
2. `quick = _merge_specs(extract_specs_from_short_text(text), extract_specs_heuristic(text))`;
3. пытается LLM;
4. `merged = _merge_specs(llm_data, quick)`;
5. `merged = _merge_specs(merged, base)`;
6. `_postprocess_specs`;
7. `merge_draft`;
8. возвращает draft + raw LLM + warning.

### 10.4 Clarification UI data

Если не хватает полей:

Backend возвращает:

- `bot_response`: текстовый fallback;
- `order_specs_clarify_preview`: структурированная версия для UI:
  - warning;
  - intro;
  - found_rows;
  - missing_title;
  - missing_hint;
  - missing_rows;
  - footer.

Особенность текущей логики:

- если числа расхода/давления уже есть, но не хватает только единицы, бот спрашивает именно:
  - "В каких единицах измеряется расход (3100-244000)";
  - "В каких единицах измеряется давление (7-15)";
- это сделано через `_UNIT_ONLY_KEYS`, `_missing_field_rows`, `_clarify_missing_hint`, `_clarify_footer`.

---

## 11. Проверка заполненности specs

Файл: `back/chatbot/api/order_specs_helpers.py`

### 11.1 is_value_missing()

Пустыми считаются:

- `None`;
- Decimal/float/int == 0;
- NaN/Inf;
- строки:
  - пустая;
  - `"0"`;
  - `"не указано"`;
  - `"не указан"`;
  - `"неизвестно"`;
  - `"отсутствует"`;
  - `n/a`, `na`;
  - `нет`;
  - `-`, `—`, `–`.

### 11.2 list_missing_fields()

```python
d = merge_draft(draft)
return [k for k in SPEC_KEYS if is_value_missing(k, d.get(k))]
```

`merge_draft()` сейчас просто `_normalize_specs(base)`. Ранее обсуждалась автоподстановка единиц, но по требованию пользователя она отменена: бот должен спрашивать единицы, а не угадывать.

### 11.3 FIELD_PROMPTS

Для классического PDF-clarify бот спрашивает поля по одному:

- medium;
- gas_type;
- flowMin;
- flowMax;
- flow_unit;
- pressureMin;
- pressureMax;
- pressure_unit;
- temperatures;
- accuracy;
- diameter.

### 11.4 Preview таблицы

`build_order_specs_preview(draft)`:

- `review_title`;
- `review_rows`;
- `footer`.

Frontend заменяет текст на таблицу через `orderSpecsConfirmTable.js`.

---

## 12. Подбор оборудования через внешний сервис

Backend helper: `back/chatbot/api/search_equipment.py`.

Frontend тоже имеет `front/chatbot/src/utils/searchEquipment.js` и вызывает API напрямую.

Backend helper строит query:

```text
equipment_type=flowmeters
medium=gas/liquid
application=industrial
gas_type=natural/technological
flowMin
flowMax
flow_unit
diameter
pressureMin
pressureMax
pressure_unit
tempMediumMin
tempMediumMax
temperature_unit
tempAmbientMin
tempAmbientMax
accuracy
```

В frontend:

- `fetchSearchEquipment(specsObject)` в `api.js`;
- URL из `REACT_APP_SEARCH_EQUIPMENT_URL`;
- логирует `[search-equipment] GET URL:`;
- timeout 120000 ms.

После `order_final` frontend вызывает `fetchSearchEquipment(specs)` и показывает слайдер оборудования.

---

## 13. Frontend ChatWidget

Файл: `front/chatbot/src/components/ChatWidget.js`

Это главный UI и orchestration-компонент.

Состояния:

- `isOpen`;
- `showGreetingTeaser`;
- `chatWindowHeight`;
- `messages`;
- `isTyping`;
- `typingStage`;
- `chatId`;
- `hintState`;
- `hintLocked`;
- `awaitingEquipmentSelection`;
- `showExactCostHint`;
- `showTkpPdfHint`;
- `isSelectingAccessories`;
- выбранные файлы, аксессуары и т.д.

refs:

- `chatIdRef`;
- `chatCreatePromiseRef`;
- `sliderEquipmentRef`;
- `lastOrderSpecsRef`;
- `exactCostBodyRef`;
- `estimateQuoteRef`;
- `pendingEstimateBodyRef`;
- `verifiedContactRef`;
- lead refs для заявок.

### 13.1 Инициализация

`initializeChat()`:

- не создаёт чат в БД сразу;
- сбрасывает refs/state;
- делает `getHints('start')`;
- добавляет приветственное bot message;
- если API недоступен, использует `FALLBACK_HINTS_START`.

`ensureChatId()`:

- создаёт Chat только при первом пользовательском действии;
- защищён от дублей через `chatCreatePromiseRef`.

### 13.2 Приветственный teaser

Недавнее изменение:

- чат не открывается автоматически;
- через 2 секунды появляется пузырь слева от круглой кнопки:

```text
Здравствуйте! Помогу подобрать оборудование или ответить на ваши вопросы.
```

- кнопка чата медленно пульсирует, пока чат закрыт;
- при открытии teaser скрывается;
- у teaser есть крестик.

CSS в `App.css`:

- `.chat-widget__greeting-teaser`;
- `.chat-widget__toggle--pulse`;
- `@keyframes chat-widget-toggle-pulse`.

### 13.3 Отправка сообщений

`addMessage(text, from, image, pdf)`:

- добавляет локальное user message;
- `ensureChatId`;
- собирает payload:
  - `content`;
  - `hint_state`;
  - `is_hint_selection`;
  - `hint_locked`;
  - вложения;
  - lead data;
  - specs/equipment для цены;
- вызывает `createMessage`;
- обрабатывает расширенный ответ backend;
- если backend вернул `order_specs_preview`, рисует таблицу;
- если `order_specs_clarify_preview`, рисует карточку уточнения;
- если `isOrderFinalWithSpecs`, вызывает `fetchSearchEquipment`.

### 13.4 Цена

Важные функции:

- `equipmentIdFromItem`;
- `buildEstimatePriceBody`;
- `buildTkpAccessoriesBody`;
- `ensureEstimateQuote`;
- `runEstimatePrice`;
- `handleGetPriceHint`;
- `handleDebugSkipEquipmentPriceVerify`.

Для `gfg2`:

```js
const EQUIPMENT_IDS_WITHOUT_PRICE = new Set(['gfg2']);
```

Если выбран `gfg2`, frontend не идёт в `estimate-price`, а выводит:

```text
К сожалению, ориентировочный прайс на оборудование «Turbo Flow GFG» пока недоступен. Для расчёта стоимости обратитесь к менеджеру.
```

### 13.5 Компоненты specs UI

`front/chatbot/src/components/orderSpecsConfirmTable.js`:

- `OrderSpecsConfirmTable`;
- `enhanceBotMessageWithOrderSpecsConfirm`;
- `shouldShowOrderSpecsBotMessage`;
- `enrichBotMessage`.

`front/chatbot/src/components/OrderSpecsTextClarify.js`:

- структурирует `order_specs_clarify_preview`;
- fallback-парсер для старого plain-text ответа;
- бежевый блок `Необходимо уточнить`;
- строки "например: ...";
- отдельный текст, что значения являются примерами.

---

## 14. Внешние интеграции

### 14.1 LM Studio

Используется для:

1. RAG Q&A.
2. Извлечения specs из PDF/DOCX.
3. Извлечения specs из свободного текста.
4. Генерации title чата.

Base URL:

```text
http://192.168.5.53:1234/v1/
```

Модель:

```text
yandexgpt-5-lite-8b-instruct
```

Важно:

- если поменять IP/порт/model в `config.yaml`, надо перезапустить Daphne;
- `LLMClient` сам добавляет `/v1`, если забыли;
- при `Model does not exist` подсказка пользователю формируется в `pdf_order_analysis.py`.

### 14.2 Сервис `:8010`

Используется из frontend и backend.

Frontend:

- `search-equipment`;
- `estimate-price`;
- `tkp-accessories`;
- `tkp-pdf`;
- `prices/grand-gas-meters`.

Backend:

- verification origin;
- submit verification liquid;
- submit household gas;
- submit SPU application;
- SPU card API.

### 14.3 Верификация email

Файл: `back/chatbot/api/verification_client.py`

POST:

- `/api/send-verification-code`;
- `/api/verify-code`.

Origin:

```python
settings.VERIFICATION_SERVICE_ORIGIN
```

По умолчанию сейчас завязан на `192.168.5.49:8010`.

---

## 15. Потоки данных

### 15.1 Обычный вопрос пользователя (RAG)

```text
Frontend ChatWidget
  -> POST /api/chats/<id>/messages/
    payload: content, hint_state=start, hint_locked=false

Backend MessageViewSet.create
  -> is_start_like=True
  -> looks_like_order_specs_request(text)?
      no:
        bot = get_chatbot()
        bot.generate_response(question)

AdvancedChatbot.generate_response
  -> is_greeting?
  -> QuestionClassifier.classify
  -> adjust_search_parameters
  -> EmbeddingModel.encode(question)
  -> smart_search
      -> ProductDetector
      -> VectorStore.search
  -> filter chunk types
  -> threshold check
  -> LLMClient.generate
  -> OpenAI-compatible request to LM Studio
  -> answer

Backend
  -> saves bot Message
  -> returns messages + hint_state

Frontend
  -> appends bot answer
```

### 15.2 Text specs подбор расходомера

```text
User: "нужен расходомер для природного газа DN300..."

MessageViewSet.create
  -> is_start_like=True
  -> looks_like_order_specs_request(text)=True
  -> _handle_order_specs_text_message
      -> get_order_specs_llm()
      -> extract_order_specs_from_text
          -> regex quick rules
          -> generic PDF heuristics
          -> LLM JSON extraction
          -> merge + postprocess
      -> list_missing_fields
      -> if missing:
           save draft
           state=order_specs_text_clarify
           return order_specs_clarify_preview
         else:
           _transition_to_order_specs_confirm

Frontend
  -> OrderSpecsTextClarify or OrderSpecsConfirmTable
```

### 15.3 PDF/DOCX specs подбор

```text
User selects "Подбор оборудования" -> "Расходомеры"
  -> state=order_pdf_request
User uploads PDF/DOCX

MessageViewSet.create
  -> current_state=order_pdf_request
  -> _is_order_specs_attachment_upload=True
  -> run_pdf_order_pipeline
      -> pdf/docx text extraction
      -> LLM extraction
      -> heuristics
      -> postprocess
  -> list_missing_fields
  -> clarify one-by-one or table confirm

Confirm
  -> order_final
  -> frontend fetchSearchEquipment
  -> equipment slider
```

### 15.4 Цена

```text
Equipment slider
  -> user clicks "Получить цену"
  -> frontend resolveEquipmentForPrice + resolveOrderSpecsForPrice
  -> if equipment.id == gfg2:
       show unavailable message
       stop
     else:
       createMessage("Получить цену", hint_selection)

Backend
  -> stores price_quote_draft
  -> asks phone
  -> asks email
  -> sends verification code
  -> verifies code
  -> returns verification_passed

Frontend
  -> runEstimatePrice
  -> POST estimate-price
  -> show approximate price
  -> allow exact cost/TKP flow
```

---

## 16. Текущие последние изменения, важные для анализа

1. Добавлен `back/chatbot/api/order_specs_text.py`.
2. Добавлен `front/chatbot/src/components/OrderSpecsTextClarify.js`.
3. Добавлен state `order_specs_text_clarify`.
4. Добавлен UI бежевого блока для уточнения недостающих параметров.
5. Для missing unit полей бот спрашивает "в каких единицах измеряется", а не "расход/давление" целиком.
6. `gfg2` / `Turbo Flow GFG` исключён из прайса на frontend.
7. Чат больше не открывается автоматически, но через 2 секунды показывает teaser bubble около кнопки.
8. Кнопка бота медленно пульсирует до открытия чата.
9. Коммит до этих последних teaser/pulse правок был:

```text
8b2794f MVP перед совещанием
```

После него есть незакоммиченные frontend-изменения.

---

## 17. Потенциальные проблемы и точки для DeepSeek-анализа

### 17.1 RAG relevance / scoring

Главный вопрос:

> Корректно ли считается score в `VectorStore.search()` при `faiss.IndexFlatIP` и нормализованных embeddings?

Сейчас:

```python
confidence = 1 - float(dist) / 2
```

При cosine similarity это выглядит неправильно. Вероятно, нужно:

- использовать `score = float(dist)` для `IndexFlatIP`;
- или если использовать L2 distance, тогда индекс должен быть `IndexFlatL2`, а формула может быть другой;
- проверить threshold после исправления.

### 17.2 Почему `top_k=1` в config

Хотя для attribute/description top_k переопределяется, для прочих вопросов `top_k=1`. Это может ухудшать ответы.

### 17.3 ProductDetector может доминировать

Product chunks получают score 0.8/0.9 вручную. Если vector score пересчитан неверно, product chunks почти всегда будут выше/ниже некорректно.

### 17.4 Нет reranking

Для технических характеристик лучше:

- hybrid retrieval: BM25 + embeddings;
- keyword boost по словам параметра;
- rerank by cross-encoder;
- отдельный поиск по `chunk_type=specifications`;
- структурированная таблица характеристик в индекс.

### 17.5 Нужна диагностика источников

Пользователю запрещено видеть chunk/context, но для админ/debug полезно:

- сохранять `last_chunks`;
- отдавать debug в dev;
- логировать top chunks с scores;
- добавить endpoint `/api/rag/debug`.

### 17.6 `back/project` как data/config + prototype

Сейчас `back/project` смешивает:

- config;
- data;
- index builder;
- standalone chat prototype.

Стоит решить:

- оставить как `rag_assets`;
- перенести build.py в management command;
- удалить/задокументировать prototype.

### 17.7 Django settings

В `settings.py`:

- `DEBUG=True`;
- hardcoded `SECRET_KEY`;
- SQLite;
- локальные IP в ALLOWED_HOSTS/CORS;
- no env-based production config.

Если production реально на PostgreSQL, текущий файл не отражает production. Нужно найти server config/deploy script.

### 17.8 RAG singleton

`_chatbot_instance` кэширует:

- config;
- LLM client;
- FAISS index;
- chunks;
- product embeddings.

После обновления:

- `config.yaml`;
- chunks;
- FAISS index;
- LM Studio model;

нужен restart Daphne или `reload_chatbot()`.

### 17.9 OCR warmup

`ApiConfig.ready()` всегда запускает EasyOCR warmup, если не установлен `ORDER_SPECS_SKIP_OCR_WARMUP=1`.

Риски:

- в dev autoreload может запускать warmup дважды;
- тяжёлая загрузка CPU/RAM;
- при проблемах EasyOCR может шуметь в логах.

### 17.10 PDF/text specs и RAG используют один LLM config

`get_order_specs_llm()` берёт тот же `llm` config, что RAG, но не грузит embeddings/FAISS.

Риски:

- max_tokens=512 может быть мало для JSON extraction;
- model, подходящая для RAG, может быть не лучшей для extraction;
- нет отдельного config для extraction.

---

## 18. Что попросить DeepSeek проанализировать

Скопировать DeepSeek следующий запрос:

```text
Ты senior backend/RAG engineer. Проанализируй этот Django/React проект чатбота.

Особенно проверь:

1. RAG pipeline:
   - корректность FAISS IndexFlatIP + normalize_embeddings;
   - формулу score в VectorStore.search;
   - threshold/top_k;
   - ProductDetector и риск смещения выдачи;
   - QuestionClassifier и настройку параметров поиска;
   - prompt LLMClient и защиту от hallucination/chain-of-thought.

2. Архитектуру backend:
   - MessageViewSet.create слишком большой;
   - state machine в hints_tree;
   - сценарии order_specs PDF/text;
   - price flow;
   - внешние сервисы :8010;
   - singleton get_chatbot;
   - production readiness.

3. Качество extraction pipeline:
   - PDF/DOCX -> OCR/text -> LLM JSON -> heuristics;
   - SPEC_KEYS и missing fields;
   - text-based extraction;
   - обработка единиц измерения.

4. Frontend integration:
   - ChatWidget как orchestrator;
   - восстановление specs/equipment;
   - order_specs UI;
   - price unavailable для gfg2;
   - greeting teaser/pulse.

5. Предложи конкретный план улучшений:
   - быстрые фиксы без большого рефакторинга;
   - среднесрочный рефакторинг;
   - улучшение RAG качества;
   - диагностика и тесты;
   - безопасность и конфиги.

Не ограничивайся общими словами. Указывай конкретные файлы, функции, риски, что поменять и почему.
```

---

## 19. Файлы, которые DeepSeek должен читать первыми

Приоритет 1 — RAG:

```text
back/chatbot/api/chatbot_core/chatbot.py
back/chatbot/api/chatbot_core/vector_store.py
back/chatbot/api/chatbot_core/llm_client.py
back/chatbot/api/chatbot_core/embeddings.py
back/chatbot/api/chatbot_core/product_detector.py
back/chatbot/api/chatbot_core/question_classifier.py
back/project/config.yaml
back/project/data/build.py
back/project/data/chunks.json
```

Приоритет 2 — backend orchestration:

```text
back/chatbot/api/views.py
back/chatbot/api/hints_tree.py
back/chatbot/api/models.py
back/chatbot/api/serializers.py
back/chatbot/api/urls.py
back/chatbot/chatbot/settings.py
```

Приоритет 3 — specs extraction:

```text
back/chatbot/api/pdf_order_analysis.py
back/chatbot/api/order_specs_text.py
back/chatbot/api/order_specs_helpers.py
back/chatbot/api/search_equipment.py
back/chatbot/api/order_specs_navigation.py
```

Приоритет 4 — frontend:

```text
front/chatbot/src/components/ChatWidget.js
front/chatbot/src/components/OrderSpecsTextClarify.js
front/chatbot/src/components/orderSpecsConfirmTable.js
front/chatbot/src/api.js
front/chatbot/src/config.js
front/chatbot/src/utils/searchEquipment.js
front/chatbot/src/App.css
```

---

## 20. Мини-карта функций по файлам

### `views.py`

- `get_chatbot()` — lazy RAG singleton.
- `get_order_specs_llm()` — lightweight LLM client for specs.
- `_handle_order_specs_text_message()` — free text specs.
- `_transition_to_order_specs_confirm()` — table confirmation.
- `MessageViewSet.create()` — central state machine.
- `ChatViewSet.finalize()` — archive/title.
- `HintsView` — hints state API.

### `chatbot_core/chatbot.py`

- `AdvancedChatbot.__init__()` — config, embeddings, FAISS, LLM.
- `AdvancedChatbot.generate_response()` — RAG answer.
- `smart_search()` — product-aware retrieval.
- `adjust_search_parameters()` — dynamic top_k/threshold/filter.
- `_faiss_readable_paths()` — Windows Unicode workaround.

### `chatbot_core/vector_store.py`

- `VectorStore.search()` — FAISS search + score.

### `chatbot_core/llm_client.py`

- `LLMClient.generate()` — prompt construction.
- `_call_llm()` — OpenAI-compatible request.
- `_strip_chain_of_thought()` — remove visible thinking.
- `_post_process_answer()` — dedupe lines.

### `pdf_order_analysis.py`

- `pdf_to_text()`;
- `_get_easyocr_reader()`;
- `warmup_easyocr_reader()`;
- `analyze_specs_with_llm()`;
- `run_pdf_order_pipeline()`;
- `_normalize_specs()`;
- `_postprocess_specs()`;
- `extract_specs_heuristic()`.

### `order_specs_text.py`

- `looks_like_order_specs_request()`;
- `extract_specs_from_short_text()`;
- `_llm_extract_text_specs()`;
- `extract_order_specs_from_text()`;
- `build_order_specs_clarify_preview()`;
- `format_text_specs_clarification()`.

### `ChatWidget.js`

- `initializeChat()`;
- `ensureChatId()`;
- `addMessage()`;
- `handleHintSelect()`;
- `handleGetPriceHint()`;
- `runEstimatePrice()`;
- `ensureEstimateQuote()`;
- `syncSliderEquipment()`;
- specs/equipment recovery helpers.

---

## 21. Рекомендации по первому улучшению RAG

Если нужно быстро повысить качество RAG без большого рефакторинга:

1. Исправить score:
   - для `IndexFlatIP` использовать `score = float(dist)`;
   - пересмотреть thresholds.

2. Увеличить config `top_k`:
   - например 5-8 для default;
   - оставить attribute 20-25.

3. Добавить debug лог:
   - question;
   - question_type;
   - product detected;
   - top chunks: id, product, type, score, first 120 chars.

4. Для attribute вопросов сначала искать `specifications`, но если пусто, fallback на все типы.

5. Добавить keyword boost:
   - если вопрос содержит `давление`, поднять chunks где content содержит `давление`, `МПа`, `бар`;
   - если `расход`, поднять `расход`, `м3/ч`, `м³/ч`;
   - если `диаметр`, поднять `DN`, `Dn`, `диаметр`.

6. Добавить тестовый набор вопросов:
   - вопрос;
   - expected product;
   - expected chunk_type;
   - expected answer contains.

7. Разнести config:
   - RAG LLM;
   - specs extraction LLM;
   - title generation LLM.

---

## 22. Рекомендации по backend-рефакторингу

`MessageViewSet.create()` слишком большой. Его стоит разделить на сервисы:

```text
api/services/
  rag_service.py
  hint_flow_service.py
  order_specs_service.py
  price_flow_service.py
  verification_flow_service.py
  application_service.py
```

Для state machine:

- оставить `hints_tree.py` только декларативным деревом;
- сложную логику вынести в handlers по state;
- унифицировать response payload.

Для RAG:

- `RagService` с методами:
  - `answer(question)`;
  - `debug_retrieve(question)`;
  - `healthcheck()`;
  - `reload()`.

Для specs:

- `OrderSpecsService.extract_from_pdf`;
- `OrderSpecsService.extract_from_text`;
- `OrderSpecsService.merge`;
- `OrderSpecsService.missing_fields`.

---

## 23. Рекомендации по тестам

Backend tests:

1. `VectorStore.search`:
   - shape 1D/2D;
   - score ordering;
   - product_filter.

2. `QuestionClassifier`:
   - attribute examples;
   - description examples;
   - comparison examples.

3. `ProductDetector`:
   - exact product;
   - noisy product;
   - no product.

4. `order_specs_text`:
   - природный газ DN300 расход давление температура точность;
   - missing unit case;
   - one-message clarification merge.

5. `pdf_order_analysis`:
   - mock LLM response;
   - JSON parse;
   - heuristic fallback.

6. `MessageViewSet` integration:
   - start RAG;
   - text specs;
   - order_specs_confirm;
   - price flow.

Frontend tests:

1. `OrderSpecsTextClarify` renders beige block.
2. `ChatWidget` does not auto-open.
3. teaser appears after 2 seconds.
4. button pulses when closed.
5. `gfg2` price unavailable message.

---

## 24. Особо важные вопросы к DeepSeek

1. Нужно ли заменить формулу `confidence = 1 - dist / 2`?
2. Как правильно подобрать thresholds после исправления score?
3. Стоит ли оставить ProductDetector на embeddings или заменить на hybrid exact/fuzzy matching?
4. Как лучше индексировать structured specs:
   - отдельные chunks per parameter;
   - JSON metadata;
   - отдельный keyword index?
5. Нужно ли отдавать пользователю источники или только логировать?
6. Как разделить RAG Q&A и extraction LLM по configs?
7. Как минимально разрезать `MessageViewSet.create()` без поломки сценариев?
8. Как сделать reproducible build FAISS:
   - versioned chunks;
   - checksum;
   - index metadata.
9. Как оформить production config:
   - env vars;
   - PostgreSQL;
   - SECRET_KEY;
   - DEBUG=False;
   - ALLOWED_HOSTS/CORS.
10. Как добавить observability:
    - timing;
    - top chunks;
    - LLM errors;
    - request IDs.

---

## 25. Краткий вывод

Проект уже содержит рабочий чатбот с несколькими сложными сценариями и RAG. Основной backend технически рабочий, но монолитный: вся orchestration-логика сосредоточена в `MessageViewSet.create()`. RAG реализован достаточно просто: sentence-transformers + FAISS + product detection + prompt в LM Studio. Самая вероятная критическая проблема качества RAG — некорректная интерпретация FAISS score при `IndexFlatIP`. Второй важный риск — отсутствие reranking/hybrid search и сильное влияние ProductDetector.

Если DeepSeek будет анализировать только одну часть, начинать нужно с:

```text
back/chatbot/api/chatbot_core/vector_store.py
back/chatbot/api/chatbot_core/chatbot.py
back/project/config.yaml
back/project/data/build.py
back/project/data/chunks.json
```

И главный технический вопрос:

```text
Как правильно пересчитать retrieval score и thresholds для текущей схемы normalized embeddings + FAISS IndexFlatIP?
```

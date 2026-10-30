# Turbo-Don Chatbot — полный реестр возможностей для ОПЭ

> **Назначение документа:** единый источник правды о функциональности проекта «Турбо-дон чат» для объектно-промышленной эксплуатации (ОПЭ).  
> **Аудитория:** тестировщики, инженеры внедрения, заказчик, ИИ-ассистенты для генерации чек-листов, протоколов и сценариев приёмки.  
> **Версия снимка:** `master-podbora`, июль 2026.  
> **Связанные документы:** `TZ_chatbot_Turbo_Don.md`, `RAG_PIPELINE.md`, `DEEPSEEK_PROJECT_ANALYSIS.md`.

---

## 0. Инструкция для ИИ (как использовать этот файл)

При генерации документов для проверки пользователями **обязательно**:

1. Брать **ID модуля** (`MOD-XX`) и **ID сценария** (`SC-XX-YY`) из раздела 4 — они являются ключами трассировки к ТЗ (`FR-XX`, `AC-XX`).
2. Для каждого сценария формировать таблицу: *Шаг → Действие пользователя → Ожидаемый результат → Критерий приёмки (да/нет) → Фактический результат → Комментарий*.
3. Учитывать **статус реализации**: `ГОТОВО` / `ЧАСТИЧНО` / `В РАЗРАБОТКЕ` / `НЕ РЕАЛИЗОВАНО`.
4. Разделять проверки на **обязательные для ОПЭ** (критический путь) и **расширенные** (регресс, негативные кейсы).
5. Не смешивать контуры: **RAG-консультация**, **подбор расходомеров**, **поверочные установки**, **FAQ**, **маски конкурентов** — это разные пайплайны.
6. Указывать **зависимости инфраструктуры** (раздел 2): без LM Studio, PostgreSQL, FastAPI `:8010` часть сценариев недоступна.
7. При проверке RAG использовать **контрольные вопросы** из раздела 5.4 и учитывать известные пробелы (раздел 8).

**Шаблон протокола ОПЭ (для генерации):**

```markdown
## Протокол проверки: [название сценария]
- ID: SC-XX-YY
- Модуль: MOD-XX
- Проверяющий: ___
- Дата: ___
- Среда: prod / staging / dev
- Предусловия: ___

| № | Шаг | Действие | Ожидаемый результат | OK/FAIL | Примечание |
|---|-----|----------|---------------------|---------|------------|
| 1 | ... | ... | ... | | |
```

---

## 1. Назначение системы

**Интеллектуальный веб-чатбот** ГК «Турбулентность-ДОН» для:

- консультаций по продукции (RAG + FAQ);
- подбора промышленных расходомеров (PDF/DOCX/текст → JSON → внешний каталог);
- подбора поверочных установок СПУ (газ/жидкость);
- оформления заявок (продажа, поверка, техподдержка, претензии, вакансии, бытовые счётчики);
- получения цены и ТКП по выбранному оборудованию;
- декодирования масок конкурентов и подбора аналогов Turbo-Don;
- администрирования истории диалогов.

**Продуктовый URL (production):** `https://master-turbo-podbor.ru`  
**Django API (prod proxy):** `https://master-turbo-podbor.ru/podbor-api/`  
**FastAPI подбор/цена/ТКП:** `https://master-turbo-podbor.ru/api/`

---

## 2. Инфраструктура и запуск ОПЭ

### 2.1. Компоненты

| Компонент | Технология | Порт/URL | Роль |
|-----------|------------|----------|------|
| Frontend | React 19 (CRA) | nginx `:80` / dev `:3001` | Виджет чата, слайдер оборудования, админ-панель |
| Backend | Django 5.1 + DRF + Daphne ASGI | `:10112` (prod server), dev `:8002` | API, FSM-сценарии, RAG, файлы |
| БД | **PostgreSQL** (prod) / SQLite (локальный dev) | — | Чаты, сообщения, KnowledgeDocument |
| LLM | LM Studio (OpenAI-compatible API) | `http://192.168.5.53:1234/v1/` | RAG-ответы, извлечение спецификаций из PDF/текста |
| RAG-индекс | FAISS + chunks.json | `back/project/data/` | Семантический + BM25 гибридный поиск |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` | — | Векторизация чанков |
| Reranker | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | — | Переранжирование кандидатов RAG |
| Подбор/цена/ТКП | FastAPI (внешний сервис) | `:8010` / `master-turbo-podbor.ru/api` | search-equipment, estimate-price, tkp-pdf и др. |
| Nginx | `docker/nginx.master-podbora.conf` | `:80` | Статика React, прокси `/api/`, `/health`, `/media/` |

### 2.2. Деплой backend (production)

```powershell
# Из корня репозитория, на рабочей машине 192.168.5.53
py deploy_backend.py
```

Скрипт `deploy_backend.py`:
1. Останавливает Daphne на `:10112`
2. Выполняет `manage.py migrate`
3. Запускает `back/chatbot/run_daphne.ps1`
4. Проверяет `http://127.0.0.1:10112/health/`
5. Smoke-тест: декодирование маски конкурента РГ-Т

**Важно для ОПЭ:** настоящий production backend и PostgreSQL находятся на сервере. Локальный запуск — только для разработки.

### 2.3. Предусловия перед началом ОПЭ

| № | Проверка | Как убедиться |
|---|----------|---------------|
| P-01 | Health backend | `GET /health/` → 200 |
| P-02 | LM Studio доступен | `curl http://192.168.5.53:1234/v1/models` — модель `yandexgpt-5-lite-8b-instruct` загружена |
| P-03 | FAISS-индекс существует | `back/project/data/faiss_index.bin` на сервере |
| P-04 | chunks.json актуален | `total_chunks` ≈ 2678, `total_products` = 51 |
| P-05 | FastAPI подбор доступен | `GET .../api/search-equipment?...` отвечает |
| P-06 | Frontend открывается | Виджет чата на desktop и mobile |
| P-07 | CORS/CSRF | Запросы с домена `master-turbo-podbor.ru` проходят |
| P-08 | Email-сервис | Для сценариев цены и техподдержки (SMTP настроен) |
| P-09 | Миграции БД | `KnowledgeDocument`, Chat, Message — без ошибок |

### 2.4. Конфигурация

| Файл | Назначение |
|------|------------|
| `back/project/config.yaml` | LLM URL, FAISS paths, top_k=8, threshold=0.75, reranker |
| `back/chatbot/chatbot/settings.py` | ALLOWED_HOSTS, CORS, URL внешних сервисов `:8010` |
| `front/chatbot/.env` / `config.js` | `REACT_APP_API_URL`, URL подбора и цены |
| `back/chatbot/api/hints_tree.py` | FSM всех диалоговых сценариев |

---

## 3. Архитектура обработки сообщений

```
Пользователь → ChatWidget.js → POST /api/chats/{id}/messages/
    → MessageFlowRouter
        ├─ is_hint_selection → HintFlowHandler (кнопки меню)
        ├─ order_specs states → OrderSpecsFlowHandler (PDF/текст/DOCX)
        ├─ start / is_final → StartFlowHandler
        │     ├─ competitor_mask_service (маски конкурентов)
        │     ├─ order_specs_service (NLP-подбор из текста)
        │     ├─ faq_service (FAQ-ответы)
        │     └─ rag_service (RAG-консультация)
        └─ hint_locked → LockedFlowHandler
              ├─ OrderSpecsFlowHandler
              ├─ VerificationFlowHandler (СПУ газ/жидкость)
              ├─ PriceFlowHandler (цена: телефон→email→код)
              └─ переход по expects_input
```

**Ключевой инвариант:** RAG вызывается только для свободных вопросов в `start` или финальных состояниях, если запрос **не** распознан как подбор оборудования, FAQ или маска конкурента.

---

## 4. Реестр модулей и сценариев

### MOD-01. Главное меню и навигация FSM

**Статус:** ГОТОВО  
**Файлы:** `hints_tree.py`, `HintFlowHandler`, `ChatWidget.js`

Начальное состояние `start` — кнопки:

| Кнопка | next_state | Описание |
|--------|------------|----------|
| Подбор оборудования | `equipment_pick` | Расходомеры, СПУ, бытовые счётчики |
| Продажа оборудования | `sales` | Заявка на закупку |
| Поверка | `verification` | Поверка собственного/стороннего оборудования |
| Пуско-наладочные работы | `commissioning` | ПНР |
| Обратная связь | `feedback_pick` | Техподдержка / претензии |
| Отклик на вакансию | `vacancy` | HR-сценарий |
| Другое | `other` | Произвольный запрос |

**SC-01-01:** Открытие чата — приветствие + 7 кнопок.  
**SC-01-02:** Кнопка «Вернуться» (`show_back`) — возврат на уровень выше.  
**SC-01-03:** Финальные состояния (`is_final: true`) — повторный свободный ввод + RAG.  
**SC-01-04:** `hints_only` — поле ввода отключено, только кнопки (СПУ газ).

---

### MOD-02. RAG-консультация (интеллектуальные ответы)

**Статус:** ЧАСТИЧНО (каталог + паспорта проиндексированы; качество по паспортам — см. раздел 8)  
**Файлы:** `rag_service.py`, `chatbot_core/chatbot.py`, `hybrid_search.py`, `vector_store.py`, `product_detector.py`, `question_classifier.py`, `reranker.py`  
**Связь с ТЗ:** FR-01, FR-02, FR-10, FR-11, AC-01, AC-04, AC-08

**Возможности:**
- Гибридный поиск: BM25 + FAISS (RRF fusion)
- Cross-encoder reranker (top-40 кандидатов)
- Классификация типа вопроса: attribute / description / comparison / selection / operation
- ProductDetector — привязка к продукту из 51 модели каталога
- Буст по `source_file`, `doc_type`, странице, неисправностям
- Follow-up: уточнение модели при диагностике неисправностей
- Отображение источников RAG в UI (`RagSourcesCard.js`)
- Fallback при низкой уверенности

**База знаний (chunks.json):**
- ~2678 чанков, 51 продукт
- `doc_type`: `catalog`, `passport`, `gost`
- Источники: карточки turbo-don.ru + паспорта/РЭ/ОТ/МП из `back/project/data/documents/passport/` (~75 PDF/DOCX)

**SC-02-01:** Свободный вопрос «Какой диапазон расхода у UFG-F DN100?» → ответ с контекстом каталога.  
**SC-02-02:** Вопрос по паспорту «Какой МПИ у СПУ-5?» → цитата с указанием документа.  
**SC-02-03:** Приветствие «Здравствуйте» → шаблонный ответ без RAG.  
**SC-02-04:** Вопрос вне базы → fallback + предложение связаться.  
**SC-02-05:** Диагностика неисправности → уточнение модели → склейка контекста.  
**SC-02-06:** Карточка источников — отображаются `document_name`, страница (если есть в metadata).

---

### MOD-03. FAQ-слой (быстрые ответы без LLM)

**Статус:** ГОТОВО  
**Файлы:** `faq_service.py`  
**Связь с ТЗ:** FR-07, FR-08 (частично)

**Темы FAQ (из `чатбот вопрос-ответ.xlsx`):**

| Тема | Пример вопроса | Результат |
|------|----------------|-----------|
| Скачать ПО/документы UFG | «Где скачать РЭ UFG» | Ссылка на turbo-don.ru |
| Скачать ПО/документы TFG | «Где скачать методику поверки TFG» | Ссылка |
| Личный кабинет | «Где посмотреть настроечные параметры» | URL web1C |
| Реестр поверок | «Сведения о поверке» | fgis.gost.ru |
| Техподдержка | «Техподдержка» | Контакт Макс +79289609242 |
| Удалённая диагностика | «Что подготовить для диагностики» | Инструкция RS485, RuDesktop |
| Сервисные центры | «Как найти СЦ в городе» | Ссылка на дилера / `ServiceCenterPicker` |
| Официальное письмо | «Как написать письмо» | Адресат, info@turbo-don.ru |
| Ремонт | «Как отправить на ремонт» | Памятка (PDF-вложение бота) |
| Предварительная оценка | «Что прислать в техподдержку» | UFG Viewer отчёт, скриншот |

**SC-03-01:** Вопрос «Где скачать руководство по эксплуатации UFG» → FAQ-карточка со ссылкой.  
**SC-03-02:** «Как отправить оборудование на ремонт» → текст + скачиваемая памятка.  
**SC-03-03:** «Консультация» (hint) → переход в RAG.  
**SC-03-04:** Сервисные центры → `GET /api/service-centers/` + UI picker.

---

### MOD-04. Подбор расходомеров (PDF / DOCX / текст)

**Статус:** ГОТОВО  
**Файлы:** `order_specs_flow.py`, `order_specs_service.py`, `pdf_order_analysis.py`, `order_specs_helpers.py`, `orderSpecsConfirmTable.js`  
**Связь с ТЗ:** FR-03, FR-04, FR-05, AC-02, AC-03

**Параметры спецификации (SPEC_KEYS):**

| Поле | Обязательность | Описание |
|------|----------------|----------|
| medium | обязательно | газ / жидкость |
| gas_type | опционально | тип среды |
| duplication_type | для газа | без / частичное / полное дублирование |
| flowMin, flowMax, flow_unit | обязательно | диапазон расхода |
| pressureMin, pressureMax, pressure_unit | обязательно | давление |
| tempMediumMin/Max, tempAmbientMin/Max, temperature_unit | обязательно | температуры |
| accuracy | обязательно | класс точности |
| diameter | обязательно | DN |

**Пайплайн:**
1. Пользователь: текст или файл PDF/DOCX (до 15 МБ, `.pdf`, `.docx`)
2. PyMuPDF / EasyOCR / python-docx → текст
3. LLM → JSON спецификации
4. Уточнение недостающих полей (`order_specs_clarify` / `order_specs_text_clarify`)
5. Таблица подтверждения (`order_specs_confirm`) — редактирование полей
6. Кнопка «Подтвердить и подобрать оборудование»
7. Frontend: `GET /api/search-equipment?...` → слайдер карточек
8. Фильтр реестра Газпром (опционально)
9. Кнопка «Получить цену» → MOD-06

**SC-04-01:** Загрузка PDF опросного листа → таблица параметров.  
**SC-04-02:** Текст «газ DN100 Qmax 500 м3/ч давление 1.6 МПа» → извлечение + уточнение.  
**SC-04-03:** Редактирование поля в таблице подтверждения.  
**SC-04-04:** Подтверждение → слайдер с 1+ моделями.  
**SC-04-05:** Нет подходящих моделей → `EquipmentNoMatchCard` с анализом.  
**SC-04-06:** DOCX-файл → тот же пайплайн.  
**SC-04-07:** OCR для скан-PDF (EasyOCR).

---

### MOD-05. Маски конкурентов и аналоги Turbo-Don

**Статус:** ГОТОВО  
**Файлы:** `competitor_masks/`, `CompetitorMaskCard.js`, `CompetitorComparisonCard.js`

**Поддерживаемые каталоги:**

| catalog_id | Конкурент | Парсер |
|------------|-----------|--------|
| rg_t | РГ-Т | `parse_rg_t_mask` |
| vympel_500 | Вымпел-500 | `parse_vympel_500_mask` |
| ktm_600 | КТМ-600 | `parse_ktm_600_mask` |
| ultramag | UltraMag | `parse_ultramag_mask` |
| irvis_ultra | Ирвис-Ultra | `parse_irvis_ultra_mask` |
| rsg_signal | RSG Signal | `parse_rsg_signal_mask` |

**Возможности:**
- Декодирование маски → карточка параметров + ошибки валидации
- Сравнительная карточка Turbo-Don vs конкурент
- Маппинг на аналог → автоподбор через search-equipment

**SC-05-01:** Ввод маски РГ-Т → `competitor_mask_card` с параметрами.  
**SC-05-02:** Невалидное значение → ошибки в карточке (без галлюцинаций LLM).  
**SC-05-03:** После декодирования → слайдер аналогов Turbo-Don.  
**SC-05-04:** Сравнительная таблица характеристик.

---

### MOD-06. Получение цены и ТКП

**Статус:** ГОТОВО (зависит от FastAPI `:8010`)  
**Файлы:** `price_flow.py`, `config.js` (ESTIMATE_PRICE_URL, TKP_PDF_URL, TKP_ACCESSORIES_URL)

**Сценарий цены:**
1. Кнопка «Получить цену» на карточке оборудования
2. FSM: `equipment_price_phone` → `equipment_price_email` → `equipment_price_verify_code`
3. Отправка кода на email, верификация
4. Запрос цены на FastAPI `estimate-price`
5. Для части приборов цена недоступна на frontend (блокировка до уточнения)

**Дополнительно:**
- `tkp-pdf` — генерация PDF технико-коммерческого предложения
- `tkp-accessories` — аксессуары к ТКП
- `send-price-inquiry` — отправка запроса цены
- `qmax-hint` — подсказка по Qmax

**SC-06-01:** Полный цикл: выбор прибора → цена → телефон → email → код → ответ.  
**SC-06-02:** Невалидный email → ошибка валидации (`POST /api/validate-email/`).  
**SC-06-03:** Генерация ТКП PDF.  
**SC-06-04:** Прибор без цены — корректное сообщение пользователю.

---

### MOD-07. Поверочные установки СПУ (газ)

**Статус:** ГОТОВО  
**Файлы:** `gas_spu_wizard.py`, `gasSpuResultCard.js`, `submit_spu_application.py`

**Мастер подбора (состояние `verification_installations_gas`):**
- Выбор среды: Газ / Жидкость
- Для газа: пошаговый wizard (тип счётчиков, установка, расход SPU-3/5/7, точность, посты, линии и т.д.)
- Превью карточки СПУ через `POST .../api/spu/card`
- Кнопка «Оставить заявку →»
- Сбор ФИО, контакт, загрузка ТЗ (PDF/DOC/DOCX/TXT/ZIP/RAR до 10 МБ)
- Отправка: `POST .../api/submit-spu-application`

**SC-07-01:** Полный wizard СПУ-3 → карточка с параметрами.  
**SC-07-02:** Wizard СПУ-5 / СПУ-7 — все ветки параметров.  
**SC-07-03:** Заявка с ТЗ-файлом → успешный submit.  
**SC-07-04:** Заявка без ТЗ (кнопка «Далее») → submit.

---

### MOD-08. Поверочные установки (жидкость)

**Статус:** ЧАСТИЧНО  
**Файлы:** `verification_flow.py`, `submit_verification_liquid.py`, `LiquidTzPromptCard`

- Сбор ФИО, контакт, загрузка ТЗ
- Шаблон опросного листа: `GET /api/templates/purs-questionnaire/`
- Submit: `submit-verification-liquid`
- Сообщение: «Дальнейшие шаги для жидкости будут доступны на сайте»

**SC-08-01:** Загрузка ТЗ для жидкости.  
**SC-08-02:** Скачивание шаблона PURS.  
**SC-08-03:** Отправка заявки на FastAPI.

---

### MOD-09. Бытовые счётчики газа

**Статус:** ГОТОВО  
**Файлы:** `GrandGasMetersPriceBlock.js`, `submit_household_gas.py`

- Прайс-лист Гранд в UI
- FSM: `household_gas_fullname` → contact → organization → comment
- Submit: `POST .../api/submit-household-gas-request`
- Прайс API: `grand-gas-meters-price`

**SC-09-01:** Выбор счётчика → заявка с ФИО и контактом.  
**SC-09-02:** Отображение актуальных цен из 1C/FastAPI.

---

### MOD-10. Продажа оборудования

**Статус:** ГОТОВО  
**FSM:** `sales` → industrial/household → contact → `sales_final`

**SC-10-01:** Промышленное — организация, тип, модель, объём → контакт → финал.  
**SC-10-02:** Бытовые счётчики — аналогично.

---

### MOD-11. Поверка (метрологическая услуга)

**Статус:** ГОТОВО  
**FSM:** `verification` → own/third → заводской номер → contact → `verification_final`

**SC-11-01:** Собственное оборудование — сбор данных + контакт.  
**SC-11-02:** Стороннее оборудование — тот же поток.

---

### MOD-12. Пуско-наладочные работы (ПНР)

**Статус:** ГОТОВО  
**FSM:** `commissioning` → contact → `commissioning_final`  
**Контакт ПНР:** +7 (928) 960-92-42

**SC-12-01:** Ввод заводского номера, адреса объекта → контакт → финал.

---

### MOD-13. Техническая поддержка

**Статус:** ГОТОВО  
**FSM:** `tech_support` → industrial/household → описание проблемы → contact → `tech_support_final`  
**Интеграция:** email-уведомление при `finalize` + аналитика `ANALYTICS_SUPPORT_REQUEST_URL`

**SC-13-01:** Описание проблемы + фото (вложение image).  
**SC-13-02:** Email-нотификация сотрудникам при завершении.  
**SC-13-03:** Загрузка изображения шильдика (FR-12, AC-06).

---

### MOD-14. Претензии

**Статус:** ГОТОВО  
**FSM:** `claims` → industrial (договор, ОЛ, зав.номер, фото) / household → contact → `claims_final`

**SC-14-01:** Промышленная претензия с вложениями.  
**SC-14-02:** Бытовая — упрощённый сценарий.

---

### MOD-15. Отклик на вакансию / Другое

**Статус:** ГОТОВО  
**FSM:** `vacancy` / `other` → contact → final

**SC-15-01:** Вакансия + ссылка hh.ru → контакт.  
**SC-15-02:** Произвольный запрос в «Другое».

---

### MOD-16. Управление чатами (пользователь + админ)

**Статус:** ГОТОВО  
**Файлы:** `ChatViewSet`, `AdminPanel.js`

| API | Метод | Описание |
|-----|-------|----------|
| `/api/chats/` | GET, POST | Список / создание |
| `/api/chats/{id}/` | PUT, DELETE | Обновление / удаление |
| `/api/chats/{id}/finalize/` | POST | Заголовок LLM или удаление пустого |
| `/api/chats/{id}/generate_title/` | POST | Генерация заголовка |
| `/api/chats/{id}/archive/` | POST | Архивирование |
| `/api/chats/{id}/unarchive/` | POST | Разархивирование |
| `/api/chats/archive_old/` | POST | Автоархив >10 дней |
| `/api/chats/cleanup_empty/` | POST | Удаление пустых |
| `/api/chats/{id}/messages/` | GET, POST | История / новое сообщение |

**AdminPanel:** активные/архивные чаты, просмотр сообщений, геолокация по IP, редактирование заголовка.

**SC-16-01:** Создание чата → диалог → finalize → осмысленный заголовок.  
**SC-16-02:** Пустой чат при finalize → удаление.  
**SC-16-03:** Архивация старых чатов.  
**SC-16-04:** Админ-панель — просмотр истории.

---

### MOD-17. Файлообмен и вложения

**Статус:** ГОТОВО  
**Файлы:** `attachment_storage.py`, `Message.attachment`, `Message.image`

| Тип | Форматы | Лимит | Сценарий |
|-----|---------|-------|----------|
| image | jpg, png, ... | — | Техподдержка, претензии |
| attachment (order_specs) | PDF, DOCX | 15 МБ | Подбор расходомеров |
| attachment (liquid/gas TZ) | PDF, DOC, DOCX, TXT, ZIP, RAR | 10 МБ | Заявки СПУ |
| bot attachment | PDF | — | FAQ памятка по ремонту |

**API скачивания:**
- `/api/message-attachments/{message_id}/`
- `/api/chat-attachments/{relpath}`
- `/api/faq-attachments/repair-memo/`
- `/api/knowledge-doc/download/?key=...`
- `/api/equipment-media/{relpath}`

**SC-17-01:** Загрузка PDF опросного листа → сохранение в media.  
**SC-17-02:** Скачивание вложения бота (памятка).  
**SC-17-03:** Отклонение файла неверного формата/размера.

---

### MOD-18. Подсказки (Hints API)

**Статус:** ГОТОВО

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/api/hints/?state=start` | GET | Данные состояния FSM |
| `/api/hints/` | POST | Переход по подсказке |

**SC-18-01:** GET hints для каждого из 40+ состояний FSM.

---

### MOD-19. Разделы «в разработке»

**Статус:** В РАЗРАБОТКЕ

| Состояние | Сообщение |
|-----------|-----------|
| `equipment_densitometers_dev` | «Плотномеры» в разработке |
| `equipment_pressure_sensors_dev` | «Датчики давления» в разработке |

**SC-19-01:** Переход в раздел → информирующее сообщение, без падения UI.

---

### MOD-20. Обратная связь разработчикам

**Статус:** ГОТОВО  
**Файл:** `DeveloperContactPanel.js`, `DEVELOPER_FEEDBACK_URL`

**SC-20-01:** Отправка feedback через FastAPI endpoint.

---

## 5. RAG и база знаний — детали для ОПЭ

### 5.1. Пайплайн RAG

1. `QuestionClassifier` → тип вопроса
2. `ProductDetector` → продукт (если найден)
3. `HybridRetriever` (BM25 + FAISS, RRF)
4. Lexical rerank + document boost + equipment model lock
5. Cross-encoder reranker (если enabled)
6. Фильтрация stub-чанков
7. `LLMClient` → ответ строго по контексту
8. `rag_sources` → UI

### 5.2. Конфиг RAG (`config.yaml`)

```yaml
faiss.top_k: 8
faiss.confidence_threshold: 0.75
reranker.enabled: true
reranker.candidates: 40
llm.model: yandexgpt-5-lite-8b-instruct
llm.temperature: 0.2
llm.max_tokens: 512
```

### 5.3. KnowledgeDocument (версионирование)

Модель `KnowledgeDocument` в PostgreSQL:
- `document_key`, `display_name`, `doc_type` (gost/passport/catalog)
- `version`, `file_hash`, `is_active`
- Сервис: `KnowledgeVersionService`

### 5.4. Контрольные вопросы для RAG-ОПЭ

**Каталог (ожидается CORRECT):**
- «Какой диапазон температур у Turbo Flow UFG-F?»
- «Для каких сред предназначен UFL?»
- «Какие преимущества у TFG перед механическими счётчиками?»

**Паспорта (проверять цитирование источника):**
- «Какой межповерочный интервал у СПУ-5?» (МП 2023/2025)
- «Какие требования к месту установки СПУ-3М?» (МИ 3400-13)
- «Класс точности UFG по описанию типа?» (ОТ UFG 56432-14)

**Негативные:**
- Вопрос по несуществующему документу → fallback, не галлюцинация
- «Какой ГОСТ 99999-9999?» → честный отказ

### 5.5. Аудит качества RAG (внутренние инструменты)

| Скрипт | Назначение |
|--------|------------|
| `run_passport_rag_audit.py` | Аудит ответов по паспортам |
| `run_passport_batch_audit.py` | Пакетный аудит |
| `run_passport_full_audit.py` | Полный прогон |
| `export_passport_rag_gaps.py` | Экспорт пробелов |
| `run_rag_benchmark.py` | Бенчмарк RAG |
| `test_rag_pipeline.py` | Unit/integration тесты |

---

## 6. API-справочник (полный)

### 6.1. Django REST API (`/api/`)

| Endpoint | Методы | MOD |
|----------|--------|-----|
| `/chats/` | GET, POST | MOD-16 |
| `/chats/{id}/` | GET, PUT, PATCH, DELETE | MOD-16 |
| `/chats/{id}/messages/` | GET, POST | ALL |
| `/chats/{id}/finalize/` | POST | MOD-16 |
| `/chats/{id}/generate_title/` | POST | MOD-16 |
| `/chats/{id}/archive/` | POST | MOD-16 |
| `/chats/{id}/unarchive/` | POST | MOD-16 |
| `/chats/archive_old/` | POST | MOD-16 |
| `/chats/cleanup_empty/` | POST | MOD-16 |
| `/hints/` | GET, POST | MOD-18 |
| `/validate-email/` | POST | MOD-06 |
| `/test-email/` | POST | MOD-06 (dev) |
| `/service-centers/` | GET | MOD-03 |
| `/templates/purs-questionnaire/` | GET | MOD-08 |
| `/faq-attachments/repair-memo/` | GET | MOD-03 |
| `/knowledge-doc/download/` | GET | MOD-02 |
| `/message-attachments/{id}/` | GET | MOD-17 |
| `/chat-attachments/{path}` | GET | MOD-17 |
| `/equipment-media/{path}` | GET | MOD-04 |

### 6.2. FastAPI внешние (`master-turbo-podbor.ru/api/`)

| Endpoint | Назначение | MOD |
|----------|------------|-----|
| `/search-equipment` | Подбор расходомеров по параметрам | MOD-04 |
| `/estimate-price` | Расчёт цены | MOD-06 |
| `/send-price-inquiry` | Запрос цены | MOD-06 |
| `/tkp-pdf` | PDF ТКП | MOD-06 |
| `/tkp-accessories` | Аксессуары ТКП | MOD-06 |
| `/qmax-hint` | Подсказка Qmax | MOD-04 |
| `/spu/card` | Карточка СПУ | MOD-07 |
| `/submit-spu-application` | Заявка СПУ газ | MOD-07 |
| `/submit-verification-liquid` | Заявка СПУ жидкость | MOD-08 |
| `/submit-household-gas-request` | Заявка бытовые счётчики | MOD-09 |
| `/grand-gas-meters-price` | Прайс Гранд | MOD-09 |
| `/1c/data` | Данные 1С | MOD-09 |
| `/analytics/support-request` | Аналитика обращений | MOD-13 |
| `/developer-feedback` | Feedback | MOD-20 |

### 6.3. Служебные

| Endpoint | Описание |
|----------|----------|
| `/health/` | Healthcheck backend |
| `/admin/` | Django Admin |

---

## 7. FSM — полный список состояний (40+)

`start`, `equipment_pick`, `equipment_household_gas_dev`, `household_gas_fullname`, `household_gas_contact`, `household_gas_organization`, `household_gas_comment`, `household_gas_after_submit`, `equipment_densitometers_dev`, `equipment_pressure_sensors_dev`, `feedback_pick`, `order_pdf_request`, `order_specs_clarify`, `order_specs_text_clarify`, `order_specs_confirm`, `order_final`, `equipment_price_phone`, `equipment_price_email`, `equipment_price_verify_code`, `sales`, `sales_industrial`, `sales_household`, `sales_contact`, `sales_final`, `verification`, `verification_own`, `verification_third`, `verification_contact`, `verification_final`, `verification_installations`, `verification_installations_gas`, `verification_installations_gas_application`, `verification_installations_gas_application_contact`, `verification_installations_gas_application_tz`, `verification_installations_gas_application_tz_comments`, `verification_installations_gas_application_after_tz`, `verification_installations_liquid`, `verification_installations_liquid_contact`, `verification_installations_liquid_tz`, `verification_installations_liquid_tz_comments`, `verification_installations_liquid_after_tz`, `commissioning`, `commissioning_contact`, `commissioning_final`, `tech_support`, `tech_support_industrial`, `tech_support_household`, `tech_support_contact`, `tech_support_final`, `claims`, `claims_industrial`, `claims_household`, `claims_contact`, `claims_final`, `vacancy`, `vacancy_contact`, `vacancy_final`, `other`, `other_contact`, `other_final`, `free_chat`

---

## 8. Известные ограничения и риски для ОПЭ

| ID | Ограничение | Влияние на ОПЭ | Рекомендация |
|----|-------------|----------------|--------------|
| L-01 | RAG по паспортам: ~18% провалов аудита (640/3600) | AC-04 может не пройти на части документов | Использовать контрольный набор из раздела 5.4; фиксировать FAIL с именем файла |
| L-02 | Stub-чанки (OCR-заглушки) | Ответы без фактов по сканам | Помечать как известный дефект |
| L-03 | Плотномеры, датчики давления | MOD-19 не готов | Исключить из обязательных сценариев |
| L-04 | СПУ жидкость — урезанный сценарий | Нет полного wizard как для газа | Проверять только submit ТЗ |
| L-05 | CRM/Telegram интеграция | Заявки уходят на email/FastAPI, не в CRM | В ОПЭ проверять факт отправки, не CRM-карточку |
| L-06 | CSAT/аналитика KPI | FR-13, AC-09 частично | Расширенный тест, не блокер ОПЭ |
| L-07 | Голосовой ввод | Не реализован | N/A |
| L-08 | LM Studio single point of failure | RAG и PDF-анализ недоступны при падении LLM | Негативный тест P-02 |
| L-09 | `get_chatbot()` кэш в Daphne | Смена config.yaml без рестарта не применяется | Рестарт после смены конфига |
| L-10 | SQLite в dev settings | Локально ≠ prod PostgreSQL | ОПЭ только на prod/staging |

**Статистика аудита паспортов** (`passport_rag_gaps.md`, 2026-07-07):
- CORRECT: 51% (1835/3600)
- PARTIAL: 31% (1125/3600)
- HALLUCINATION: 7% (259)
- WRONG_TOPIC: 7% (247)

---

## 9. Матрица трассировки ТЗ → модули

| ТЗ ID | Описание | Модуль | Статус |
|-------|----------|--------|--------|
| FR-01 | Интеллектуальное консультирование | MOD-02 | ЧАСТИЧНО |
| FR-02 | Терминология | MOD-02 | ЧАСТИЧНО |
| FR-03 | Формальный подбор | MOD-04 | ГОТОВО |
| FR-04 | NLP-подбор | MOD-04 | ГОТОВО |
| FR-05 | Рекомендация модели | MOD-04 | ГОТОВО |
| FR-06 | Товарные карточки | MOD-04 | ГОТОВО |
| FR-07 | Ремонт/Поверка | MOD-03, MOD-11 | ГОТОВО |
| FR-08 | Диагностика неисправностей | MOD-02, MOD-03 | ЧАСТИЧНО |
| FR-09 | Эскалация инженеру | MOD-13 | ЧАСТИЧНО (email) |
| FR-10 | Нормативный справочник | MOD-02 | ЧАСТИЧНО |
| FR-11 | Цитирование источников | MOD-02 | ЧАСТИЧНО |
| FR-12 | Файлообмен | MOD-17 | ГОТОВО |
| FR-13 | CSAT | — | НЕ РЕАЛИЗОВАНО |
| UI-01..06 | Интерфейс | MOD-01, MOD-04 | ГОТОВО / ЧАСТИЧНО |
| AC-01..09 | Критерии приёмки | см. модули | см. раздел 8 |

---

## 10. Минимальный набор ОПЭ (критический путь)

**День 1 — Инфраструктура:** P-01..P-09  
**День 2 — Навигация и заявки:** SC-01-01, SC-10-01, SC-11-01, SC-12-01, SC-13-01, SC-14-01, SC-15-01  
**День 3 — Подбор расходомеров:** SC-04-01..04-05, SC-06-01  
**День 4 — СПУ и бытовые:** SC-07-01..03, SC-08-01, SC-09-01  
**День 5 — RAG и FAQ:** SC-02-01..04, SC-03-01..03, SC-05-01..03  
**День 6 — Админ и файлы:** SC-16-01..04, SC-17-01..03  
**День 7 — Негативные и регресс:** L-08, SC-02-04, SC-04-05, SC-19-01

---

## 11. Автотесты (pytest) — что запускать перед ОПЭ

```powershell
cd back/chatbot
py -3 -m pytest tests/ -q --tb=short
```

**Ключевые тест-файлы:**

| Файл | Покрытие |
|------|----------|
| `test_rag_pipeline.py` | RAG пайплайн |
| `test_product_detector.py` | ProductDetector |
| `test_faq_service.py`, `test_faq_api.py` | FAQ |
| `test_order_specs_intent.py` | Intent подбора |
| `test_competitor_mask_*.py` | Маски конкурентов |
| `test_price_flow_from_slider.py` | Цена |
| `test_message_attachment_upload.py` | Вложения |
| `test_tech_support_email.py` | Email техподдержки |

---

## 12. UI-компоненты frontend

| Компонент | Назначение |
|-----------|------------|
| `ChatWidget.js` | Основной виджет чата |
| `orderSpecsConfirmTable.js` | Таблица подтверждения спецификации |
| `OrderSpecsTextClarify.js` | Уточнение текстовых параметров |
| `gasSpuResultCard.js` | Карточка результата СПУ |
| `GrandGasMetersPriceBlock.js` | Прайс бытовых счётчиков |
| `CompetitorMaskCard.js` | Декодирование маски |
| `CompetitorComparisonCard.js` | Сравнение с Turbo-Don |
| `EquipmentNoMatchCard.js` | Нет подходящего оборудования |
| `RagSourcesCard.js` | Источники RAG |
| `ServiceCenterPicker.js` | Выбор сервисного центра |
| `AdminPanel.js` | Админ-панель чатов |
| `DeveloperContactPanel.js` | Обратная связь |
| `Header.js` | Шапка приложения |

---

## 13. Структура репозитория (для навигации)

```
master-podbora/
├── OPE_CAPABILITIES.md          ← этот файл
├── TZ_chatbot_Turbo_Don.md      ← ТЗ заказчика
├── RAG_PIPELINE.md              ← детали RAG
├── deploy_backend.py            ← деплой production
├── docker/nginx.master-podbora.conf
├── back/
│   ├── chatbot/                 ← Django backend
│   │   ├── api/
│   │   │   ├── views.py, urls.py, models.py
│   │   │   ├── hints_tree.py    ← FSM
│   │   │   ├── chatbot_core/    ← RAG ядро
│   │   │   ├── services/        ← flow handlers
│   │   │   ├── competitor_masks/
│   │   │   └── gas_spu_wizard.py
│   │   └── tests/               ← тесты и аудит RAG
│   └── project/
│       ├── config.yaml
│       └── data/
│           ├── chunks.json
│           ├── faiss_index.bin
│           └── documents/passport/
└── front/chatbot/               ← React frontend
    └── src/
        ├── api.js, config.js
        └── components/
```

---

## 14. Глоссарий

| Термин | Значение |
|--------|----------|
| ОПЭ | Объектно-промышленная эксплуатация — опытная эксплуатация у заказчика |
| RAG | Retrieval-Augmented Generation — ответ LLM на основе найденных документов |
| FSM | Finite State Machine — дерево состояний диалога (`hints_tree`) |
| СПУ | Стационарная поверочная установка |
| SPEC_KEYS | JSON-поля спецификации расходомера для подбора |
| Маска | Кодировочная строка параметров прибора конкурента |
| Чанк | Фрагмент текста в базе знаний RAG |
| ТКП | Технико-коммерческое предложение |

---

*Документ сгенерирован для проекта Turbo-Don Chatbot. При изменении кода обновляйте разделы 4, 6, 8 и матрицу раздела 9.*

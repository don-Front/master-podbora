# База аудита RAG по `passport/` — для анализа пробелов

## Статус прогона

Пакетный аудит: **75 файлов × 50 вопросов** (~6 ч). Команда:

```bash
cd back/chatbot
py tests/run_passport_batch_audit.py --start-index 3 --questions 50 --regen-questions --resume
```

Полный прогон с нуля (все файлы):

```bash
py tests/run_passport_full_audit.py --questions 50 --regen-questions
```

После прерывания — `--resume` (дописывает незавершённые JSON).

## Артефакты для анализа

| Файл | Назначение |
|------|------------|
| `passport_rag_gaps.json` | **Главная база пробелов**: провалы по bug_type, худшие файлы, retrieval miss |
| `passport_rag_gaps.md` | Краткая сводка для человека |
| `passport_batch_summary.json` | Accuracy/retrieval по каждому файлу |
| `passport_file_audit_results/*.json` | Полные ответы (50 вопросов × файл) |
| `passport_file_audit_reports/*.md` | Отчёт по файлу |

Обновить базу пробелов вручную:

```bash
py tests/export_passport_rag_gaps.py
```

## Как искать пробелы

1. **`passport_rag_gaps.json` → `worst_files`** — файлы с низким accuracy/retrieval (переименование, re-index).
2. **`failures_by_bug.retrieval`** — retrieval не нашёл нужный документ.
3. **`failures_by_bug.wrong_topic`** — нашёл другой прибор/документ (product_detector).
4. **`retrieval_misses_sample`** — вопросы без попадания в source_file.
5. **FAQ-ответы** (~150 ms, пустые `rag_sources`) — обход RAG, править flow_router.

## Ожидаемый объём

- ~75 × 50 = **3750** вопросов
- ~19 MB JSON (оценка)

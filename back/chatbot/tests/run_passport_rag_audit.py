# -*- coding: utf-8 -*-
"""
Аудит качества RAG по документам passport/ с LLM-as-judge.

Запуск из back/chatbot:
  py tests/run_passport_rag_audit.py --limit 40
  py tests/run_passport_rag_audit.py --resume
  py tests/run_passport_rag_audit.py --full
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_CHATBOT_DIR = os.path.normpath(os.path.join(_TESTS_DIR, ".."))
if _CHATBOT_DIR not in sys.path:
    sys.path.insert(0, _CHATBOT_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot.settings")

from api.chatbot_core.chatbot import AdvancedChatbot  # noqa: E402
from api.chatbot_core.llm_client import LLMClient  # noqa: E402
from tests.run_rag_benchmark import (  # noqa: E402
    _CONFIG_PATH,
    _chunk_source,
    _key_matches,
    _load_questions,
    _norm,
    _quality_label,
    _safe_console,
)

_PASSPORT_QUESTIONS = os.path.join(_TESTS_DIR, "passport_rag_questions.json")
_CHUNKS_PATH = os.path.normpath(os.path.join(_CHATBOT_DIR, "..", "project", "data", "chunks.json"))
_OUTPUT = os.path.join(_TESTS_DIR, "passport_rag_audit_results.json")
_CANVAS_DATA = os.path.join(_TESTS_DIR, "passport_rag_audit_canvas_data.json")

_FALLBACK_MARKERS = (
    "не удалось найти информации",
    "временно недоступен",
    "произошла ошибка",
    "чатбот временно недоступен",
)

_DEFAULT_API = os.environ.get(
    "PODBOR_API_BASE",
    "https://master-turbo-podbor.ru/podbor-api",
)

_JUDGE_PROMPT = """Ты — строгий аудитор RAG-чатбота по технической документации.

Вопрос пользователя:
{question}

Ожидаемые факты (эталон, не обязательно дословно):
{expected_keys}

Фрагменты контекста (retrieval):
{context}

Ответ бота:
{answer}

Оцени ответ по критериям:
- CORRECT — отвечает на вопрос, факты согласуются с контекстом
- PARTIAL — частично верно или неполно
- WRONG_TOPIC — отвечает на другой вопрос / другой прибор / другой документ
- HALLUCINATION — выдуманные факты, не подтверждённые контекстом
- NO_ANSWER — отказ, fallback, «не найдено», пустой ответ
- STUB_ONLY — только метаданные документа без содержания (тип passport, имя файла)

Верни ТОЛЬКО JSON:
{{"verdict":"...", "bug_type":"none|retrieval|wrong_product|wrong_topic|hallucination|stub|fallback|partial", "reason":"кратко по-русски"}}"""


def _load_chunks() -> list[dict]:
    raw = json.load(open(_CHUNKS_PATH, encoding="utf-8"))
    return raw if isinstance(raw, list) else raw.get("chunks") or []


def _passport_files_meta() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for ch in _load_chunks():
        meta = ch.get("metadata") or {}
        if meta.get("doc_type") != "passport":
            continue
        sf = meta.get("source_file") or ""
        if not sf:
            continue
        row = out.setdefault(
            sf,
            {
                "source_file": sf,
                "is_stub": bool(meta.get("is_text_stub")),
                "document_kind": meta.get("document_kind") or "unknown",
                "product_title": meta.get("product_title") or "",
                "chunk_count": 0,
            },
        )
        row["chunk_count"] += 1
        if meta.get("is_text_stub"):
            row["is_stub"] = True
    return out


def _supplement_questions(files_meta: dict[str, dict], covered: set[str]) -> list[dict]:
    """По 1–2 вопроса на каждый passport-файл вне набора РЭ."""
    extra: list[dict] = []
    qid = 10000
    templates = [
        (
            "срок действия",
            "Какой срок действия утверждения типа или сертификата указан в документе «{title}»?",
            ["срок", "действ", "до"],
        ),
        (
            "изготовитель",
            "Кто указан как изготовитель или правообладатель в документе «{title}»?",
            ["Турбулентность", "изготов", "право"],
        ),
        (
            "номер документа",
            "Какой регистрационный или сертификационный номер указан в документе «{title}»?",
            ["номер", "№", "регистр"],
        ),
        (
            "методика поверки",
            "Какая методика поверки или документ на поверку указаны в «{title}»?",
            ["методик", "поверк", "МП"],
        ),
        (
            "назначение СПУ",
            "Для чего предназначена установка или прибор согласно документу «{title}»?",
            ["поверк", "измер", "назнач"],
        ),
    ]
    for sf, meta in sorted(files_meta.items()):
        if sf in covered:
            continue
        title = sf.replace(".pdf", "").replace(".PDF", "").replace(".docx", "")
        kind = meta.get("document_kind") or ""
        is_stub = meta.get("is_stub")
        picks = templates[:2] if is_stub else templates[:3]
        if "методик" in kind or "МП" in sf or "методика" in sf.lower():
            picks = [templates[3], templates[0]]
        elif "СПУ" in sf or "ПУРС" in sf or "Гранд" in sf:
            picks = [templates[4], templates[0], templates[1]]
        for topic, tpl, keys in picks:
            qid += 1
            extra.append(
                {
                    "source_file": sf,
                    "id": qid,
                    "topic": topic,
                    "question": tpl.format(title=title),
                    "expected_keys": keys,
                    "is_stub_doc": is_stub,
                    "document_kind": kind,
                    "auto_generated": True,
                }
            )
    return extra


def _build_question_set(full: bool, limit: int | None) -> list[dict]:
    base = _load_questions(_PASSPORT_QUESTIONS)
    covered = {q["source_file"] for q in base}
    meta = _passport_files_meta()
    extra = _supplement_questions(meta, covered)
    if full:
        combined = base + extra
    else:
        step = max(1, len(base) // 55)
        base_sample = base[::step]
        combined = base_sample + extra
        cap = limit or 100
        combined = combined[:cap]
    return combined


def _context_preview(chunks: list[dict], limit: int = 3) -> str:
    parts: list[str] = []
    for i, ch in enumerate(chunks[:limit], 1):
        meta = ch.get("metadata") or {}
        sf = meta.get("source_file") or _chunk_source(ch)
        page = meta.get("page_number")
        text = (ch.get("text") or ch.get("content") or "")[:600]
        parts.append(f"[{i}] {sf} p.{page}\n{text}")
    return "\n\n---\n\n".join(parts) if parts else "(контекст пуст)"


def _heuristic_judge(item: dict, answer: str, retrieval_hit: bool, key_ratio: float, is_fallback: bool) -> dict[str, str]:
    ans = _norm(answer)
    if is_fallback or not answer.strip():
        return {"verdict": "NO_ANSWER", "bug_type": "fallback", "reason": "fallback или пустой ответ"}
    if "тип документа: passport" in ans or "тип документа passport" in ans:
        return {"verdict": "STUB_ONLY", "bug_type": "stub", "reason": "ответ только по метаданным stub-чанка"}
    if retrieval_hit and key_ratio >= 0.66:
        return {"verdict": "CORRECT", "bug_type": "none", "reason": "retrieval + ключевые факты совпали"}
    if key_ratio >= 0.5:
        return {"verdict": "PARTIAL", "bug_type": "partial", "reason": "часть ключевых фактов найдена"}
    if not retrieval_hit and key_ratio < 0.34:
        return {
            "verdict": "WRONG_TOPIC",
            "bug_type": "retrieval" if not retrieval_hit else "wrong_topic",
            "reason": "не тот документ или ответ мимо вопроса",
        }
    if key_ratio == 0 and len(answer) > 120:
        return {"verdict": "HALLUCINATION", "bug_type": "hallucination", "reason": "развёрнутый ответ без ключевых фактов"}
    return {"verdict": "PARTIAL", "bug_type": "partial", "reason": "неполный ответ"}


def _source_file_tokens(name: str) -> list[str]:
    stem = re.sub(r"\.(pdf|docx|PDF|DOCX)$", "", name or "")
    return [t for t in re.split(r"[\s_\-«»().]+", stem.lower()) if len(t) >= 3]


def _retrieval_from_sources(expected_file: str, rag_sources: list[dict]) -> tuple[bool, list[str]]:
    tokens = _source_file_tokens(expected_file)
    titles: list[str] = []
    hit = False
    for src in rag_sources or []:
        title = str(src.get("title") or "")
        desc = str(src.get("description") or "")
        blob = _norm(f"{title} {desc} {src.get('id', '')}")
        titles.append(title or desc or str(src.get("id") or ""))
        if not tokens:
            continue
        matched = sum(1 for t in tokens if t in blob)
        if matched >= max(1, len(tokens) // 2):
            hit = True
    return hit, titles[:5]


def _api_call_with_retry(fn, *, retries: int = 8, base_delay: float = 2.0):
    """Повтор API-вызова при 5xx/сетевых сбоях (длинный batch на prod)."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt + 1 >= retries:
                break
            delay = min(base_delay * (2**attempt), 60.0)
            print(f"[api-retry] attempt {attempt + 1}/{retries} failed: {exc}; sleep {delay:.0f}s")
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _api_create_chat(base: str) -> int:
    def _call() -> int:
        req = urllib.request.Request(
            f"{base.rstrip('/')}/api/chats/",
            data=json.dumps({"title": "passport-rag-audit"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["id"]

    return _api_call_with_retry(_call)


def _api_ask(base: str, chat_id: int, question: str) -> tuple[str, list[dict], float]:
    payload = json.dumps(
        {
            "content": question,
            "hint_state": "start",
            "hint_locked": False,
            "is_hint_selection": False,
        }
    ).encode()

    def _call() -> tuple[str, list[dict], float]:
        req = urllib.request.Request(
            f"{base.rstrip('/')}/api/chats/{chat_id}/messages/",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        total_ms = (time.perf_counter() - t0) * 1000
        bot = next(m for m in data.get("messages") or [] if not m.get("is_user"))
        answer = bot.get("content") or ""
        sources = data.get("rag_sources") or []
        return answer, sources, total_ms

    return _api_call_with_retry(_call, retries=5)


def _judge_answer(
    judge: LLMClient,
    item: dict,
    answer: str,
    chunks: list[dict],
) -> dict[str, Any]:
    prompt = _JUDGE_PROMPT.format(
        question=item.get("question", ""),
        expected_keys=", ".join(item.get("expected_keys") or []),
        context=_context_preview(chunks),
        answer=(answer or "")[:2500],
    )
    try:
        raw = judge._call_llm(prompt)
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            data = json.loads(m.group(0))
            return {
                "verdict": str(data.get("verdict") or "PARTIAL"),
                "bug_type": str(data.get("bug_type") or "none"),
                "reason": str(data.get("reason") or "")[:400],
            }
    except Exception as exc:
        return {"verdict": "ERROR", "bug_type": "judge_error", "reason": str(exc)[:200]}
    return {"verdict": "ERROR", "bug_type": "judge_error", "reason": "parse failed"}


def _judge_combined(
    judge: LLMClient | None,
    item: dict,
    answer: str,
    chunks: list[dict],
    rag_sources: list[dict] | None = None,
) -> dict[str, Any]:
    llm_result: dict[str, str] | None = None
    if judge is not None:
        llm_result = _judge_answer(judge, item, answer, chunks)
        if llm_result.get("verdict") not in ("ERROR",):
            return llm_result
    keys = item.get("expected_keys") or []
    key_hits = sum(1 for k in keys if _key_matches(k, answer))
    key_ratio = key_hits / len(keys) if keys else 0.0
    ans = _norm(answer)
    is_fallback = not answer.strip() or any(m in ans for m in _FALLBACK_MARKERS)
    if rag_sources is not None:
        retrieval_hit, _ = _retrieval_from_sources(item.get("source_file", ""), rag_sources)
    else:
        top_sources = [_chunk_source(c) for c in chunks[:8]]
        retrieval_hit = item.get("source_file", "") in top_sources
    return _heuristic_judge(item, answer, retrieval_hit, key_ratio, is_fallback)


def _score_row(
    item: dict,
    answer: str,
    chunks: list[dict],
    judge: dict,
    total_ms: float,
    rag_sources: list[dict] | None = None,
) -> dict:
    keys = item.get("expected_keys") or []
    ans = _norm(answer)
    is_fallback = not answer.strip() or any(m in ans for m in _FALLBACK_MARKERS)
    key_hits = sum(1 for k in keys if _key_matches(k, answer))
    key_total = len(keys)
    key_ratio = key_hits / key_total if key_total else 0.0
    if rag_sources is not None:
        retrieval_hit, top_titles = _retrieval_from_sources(item.get("source_file", ""), rag_sources)
        top_sources = top_titles
    else:
        top_sources = [_chunk_source(c) for c in chunks[:8]]
        retrieval_hit = item.get("source_file", "") in top_sources
    expected = item.get("source_file", "")
    heuristic = _quality_label(retrieval_hit, key_ratio, is_fallback, key_hits=key_hits, key_total=key_total)
    return {
        "source_file": expected,
        "id": item.get("id"),
        "topic": item.get("topic", ""),
        "question": item.get("question", ""),
        "expected_keys": keys,
        "answer_preview": (answer or "")[:500],
        "is_fallback": is_fallback,
        "key_hits": key_hits,
        "key_total": key_total,
        "key_ratio": round(key_ratio, 3),
        "retrieval_hit": retrieval_hit,
        "retrieval_rank": 1 if retrieval_hit else None,
        "top_sources": top_sources[:5],
        "total_ms": round(total_ms, 1),
        "heuristic_quality": heuristic,
        "judge_verdict": judge.get("verdict"),
        "bug_type": judge.get("bug_type"),
        "judge_reason": judge.get("reason"),
        "rag_sources_count": len(rag_sources or []),
        "auto_generated": bool(item.get("auto_generated")),
        "is_stub_doc": bool(item.get("is_stub_doc")),
        "document_kind": item.get("document_kind") or "",
    }


def _aggregate(results: list[dict]) -> dict[str, Any]:
    verdicts = Counter(r.get("judge_verdict") for r in results)
    bugs = Counter(r.get("bug_type") for r in results if r.get("bug_type") not in ("none", "partial"))
    by_file: dict[str, list] = defaultdict(list)
    for r in results:
        by_file[r["source_file"]].append(r)

    per_file = []
    for sf, items in sorted(by_file.items()):
        n = len(items)
        ok = sum(1 for i in items if i.get("judge_verdict") == "CORRECT")
        partial = sum(1 for i in items if i.get("judge_verdict") == "PARTIAL")
        bad = n - ok - partial
        per_file.append(
            {
                "source_file": sf,
                "questions": n,
                "correct": ok,
                "partial": partial,
                "bad": bad,
                "accuracy_pct": round(100 * ok / n, 1) if n else 0,
                "retrieval_pct": round(
                    100 * sum(1 for i in items if i["retrieval_hit"]) / n, 1
                )
                if n
                else 0,
                "top_bugs": Counter(
                    i.get("bug_type") for i in items if i.get("bug_type") not in ("none",)
                ).most_common(3),
            }
        )

    total = len(results)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_questions": total,
        "verdict_counts": dict(verdicts),
        "bug_counts": dict(bugs),
        "accuracy_pct": round(100 * verdicts.get("CORRECT", 0) / total, 1) if total else 0,
        "partial_pct": round(100 * verdicts.get("PARTIAL", 0) / total, 1) if total else 0,
        "bad_pct": round(
            100
            * sum(
                verdicts.get(v, 0)
                for v in ("WRONG_TOPIC", "HALLUCINATION", "NO_ANSWER", "STUB_ONLY", "ERROR")
            )
            / total,
            1,
        )
        if total
        else 0,
        "per_file": per_file,
        "failure_samples": [
            {
                "question": r["question"][:120],
                "source_file": r["source_file"],
                "verdict": r.get("judge_verdict"),
                "bug_type": r.get("bug_type"),
                "reason": r.get("judge_reason"),
                "top_sources": r.get("top_sources"),
            }
            for r in results
            if r.get("judge_verdict") not in ("CORRECT", "PARTIAL")
        ][:30],
        "results": results,
    }


def _save_canvas_data(summary: dict) -> None:
    canvas = {
        "summary": {
            "accuracy_pct": summary.get("accuracy_pct"),
            "partial_pct": summary.get("partial_pct"),
            "bad_pct": summary.get("bad_pct"),
            "total": summary.get("total_questions"),
            "verdict_counts": summary.get("verdict_counts"),
            "bug_counts": summary.get("bug_counts"),
        },
        "verdict_chart": [
            {"label": k, "value": v} for k, v in (summary.get("verdict_counts") or {}).items()
        ],
        "bug_chart": [
            {"label": k, "value": v}
            for k, v in (summary.get("bug_counts") or {}).items()
            if k not in ("none", "partial")
        ],
        "per_file": (summary.get("per_file") or [])[:40],
        "failures": summary.get("failure_samples") or [],
    }
    with open(_CANVAS_DATA, "w", encoding="utf-8") as f:
        json.dump(canvas, f, ensure_ascii=False, indent=2)


def run_audit(
    resume: bool = False,
    limit: int | None = None,
    full: bool = False,
    api_base: str | None = None,
    fresh: bool = False,
    use_llm_judge: bool = False,
) -> dict:
    questions = _build_question_set(full=full, limit=limit)
    done: set[tuple] = set()
    results: list[dict] = []
    if fresh and os.path.isfile(_OUTPUT):
        os.remove(_OUTPUT)
    if resume and os.path.isfile(_OUTPUT):
        prev = json.load(open(_OUTPUT, encoding="utf-8"))
        results = prev.get("results") or []
        for r in results:
            if r.get("judge_verdict") == "ERROR" and r.get("bug_type") == "judge_error":
                continue
            done.add((r.get("source_file"), r.get("id")))

    judge: LLMClient | None = None
    bot: AdvancedChatbot | None = None
    chat_id: int | None = None

    if api_base:
        chat_id = _api_create_chat(api_base)
        print(f"[passport-audit] API {api_base} chat_id={chat_id}")
    else:
        bot = AdvancedChatbot(_CONFIG_PATH)
        if use_llm_judge and bot.config:
            llm_cfg = bot.config.get("llm") or {}
            judge = LLMClient(
                base_url=llm_cfg.get("base_url", ""),
                model=llm_cfg.get("model", ""),
                temperature=0.0,
                max_tokens=256,
                timeout=int(llm_cfg.get("timeout", 90)),
            )

    print(f"[passport-audit] вопросов: {len(questions)}, готово: {len(done)}")

    for idx, item in enumerate(questions, 1):
        key = (item.get("source_file"), item.get("id"))
        if key in done:
            continue
        q = item.get("question", "")
        print(_safe_console(f"[{idx}/{len(questions)}] {item.get('source_file')} :: {q[:70]}..."), flush=True)
        chunks: list[dict] = []
        rag_sources: list[dict] | None = None
        try:
            if api_base and chat_id is not None:
                answer, rag_sources, total_ms = _api_ask(api_base, chat_id, q)
            elif bot is not None:
                t0 = time.perf_counter()
                answer = bot.generate_response(q)
                total_ms = (time.perf_counter() - t0) * 1000
                chunks = getattr(bot, "last_chunks", []) or []
            else:
                raise RuntimeError("Не задан api_base и локальный бот недоступен")
        except (urllib.error.URLError, TimeoutError, Exception) as exc:
            answer = f"ERROR: {exc}"
            total_ms = 0.0
        judge_result = _judge_combined(judge, item, answer, chunks, rag_sources)
        row = _score_row(item, answer, chunks, judge_result, total_ms, rag_sources)
        results.append(row)
        done.add(key)
        summary = _aggregate(results)
        with open(_OUTPUT, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(
            f"  -> judge={row['judge_verdict']} bug={row['bug_type']} "
            f"ret={row['retrieval_hit']} keys={row['key_hits']}/{row['key_total']} "
            f"{row['total_ms']:.0f}ms"
        )

    final = _aggregate(results)
    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    _save_canvas_data(final)
    print(f"[passport-audit] saved {_OUTPUT}")
    return final


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--resume", action="store_true")
    p.add_argument("--fresh", action="store_true", help="удалить старый результат")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--full", action="store_true", help="все 140 РЭ + авто-вопросы по остальным passport PDF")
    p.add_argument("--api", default=_DEFAULT_API, help="базовый URL API (prod). Пустая строка = локальный бот")
    p.add_argument("--llm-judge", action="store_true", help="LLM-судья (только локально)")
    args = p.parse_args()
    api_base = (args.api or "").strip() or None
    s = run_audit(
        resume=args.resume,
        limit=args.limit,
        full=args.full,
        api_base=api_base,
        fresh=args.fresh,
        use_llm_judge=args.llm_judge,
    )
    print(
        f"\nAccuracy(CORRECT)={s.get('accuracy_pct')}% "
        f"partial={s.get('partial_pct')}% bad={s.get('bad_pct')}% "
        f"total={s.get('total_questions')}"
    )
    print("Top bugs:", s.get("bug_counts"))


if __name__ == "__main__":
    main()

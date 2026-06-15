"""
Полный RAG-бенчмарк: 20 вопросов × N PDF.

Запуск из back/chatbot:
  py tests/run_rag_benchmark.py
  py tests/run_rag_benchmark.py --resume
  py tests/run_rag_benchmark.py --questions tests/rag_benchmark_questions.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

# Django не нужен — импорт напрямую из api
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_CHATBOT_DIR = os.path.normpath(os.path.join(_TESTS_DIR, ".."))
if _CHATBOT_DIR not in sys.path:
    sys.path.insert(0, _CHATBOT_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot.settings")

from api.chatbot_core.chatbot import AdvancedChatbot  # noqa: E402

_CONFIG_PATH = os.path.normpath(
    os.path.join(_CHATBOT_DIR, "..", "project", "config.yaml")
)
_DEFAULT_QUESTIONS = os.path.join(_TESTS_DIR, "rag_benchmark_questions.json")
_DEFAULT_OUTPUT = os.path.join(_TESTS_DIR, "rag_benchmark_results.json")
_FALLBACK_MARKERS = (
    "не удалось найти информации",
    "временно недоступен",
    "произошла ошибка",
)


def _norm(s: str) -> str:
    return (s or "").lower().replace("ё", "е")


def _key_matches(key: str, answer: str) -> bool:
    k = _norm(key)
    a = _norm(answer)
    if not k or not a:
        return False
    if k in a:
        return True
    k_compact = re.sub(r"[^\wа-яё0-9]+", "", k)
    a_compact = re.sub(r"[^\wа-яё0-9]+", "", a)
    if len(k_compact) >= 3 and k_compact in a_compact:
        return True
    for token in re.findall(r"[a-zа-яё0-9]{3,}", k):
        if token in a:
            return True
    return False


def _safe_console(text: str) -> str:
    return (text or "").encode("cp1251", "replace").decode("cp1251")


def _chunk_source(chunk: dict) -> str:
    meta = chunk.get("metadata") or {}
    return meta.get("source_file") or chunk.get("source_file") or ""


def _score_item(
    item: dict,
    answer: str,
    chunks: list[dict],
    total_ms: float,
    llm_ms: float,
) -> dict[str, Any]:
    expected_file = item.get("source_file", "")
    keys = item.get("expected_keys") or []
    ans = _norm(answer)
    is_fallback = not answer.strip() or any(m in ans for m in _FALLBACK_MARKERS)

    key_hits = sum(1 for k in keys if _key_matches(k, answer))
    key_total = len(keys)
    key_ratio = key_hits / key_total if key_total else 0.0

    top_sources = [_chunk_source(c) for c in chunks[:8]]
    retrieval_hit = expected_file in top_sources
    retrieval_rank = (
        top_sources.index(expected_file) + 1 if retrieval_hit else None
    )

    return {
        "source_file": expected_file,
        "id": item.get("id"),
        "topic": item.get("topic", ""),
        "question": item.get("question", ""),
        "expected_keys": keys,
        "answer_preview": (answer or "")[:500],
        "answer_len": len(answer or ""),
        "is_fallback": is_fallback,
        "key_hits": key_hits,
        "key_total": key_total,
        "key_ratio": round(key_ratio, 3),
        "retrieval_hit": retrieval_hit,
        "retrieval_rank": retrieval_rank,
        "top_sources": top_sources[:5],
        "total_ms": round(total_ms, 1),
        "llm_ms": round(llm_ms, 1),
        "quality": _quality_label(
            retrieval_hit, key_ratio, is_fallback, key_hits=key_hits, key_total=key_total
        ),
    }


def _quality_label(
    retrieval_hit: bool,
    key_ratio: float,
    is_fallback: bool,
    *,
    key_hits: int = 0,
    key_total: int = 0,
) -> str:
    if is_fallback:
        return "fail"
    if retrieval_hit:
        return "good"
    if key_ratio >= 0.5:
        return "partial"
    return "weak"


def _aggregate(results: list[dict]) -> dict[str, Any]:
    by_file: dict[str, list] = defaultdict(list)
    for r in results:
        by_file[r["source_file"]].append(r)

    per_file = []
    for sf, items in sorted(by_file.items()):
        n = len(items)
        ret = sum(1 for i in items if i["retrieval_hit"])
        good = sum(1 for i in items if i["quality"] == "good")
        partial = sum(1 for i in items if i["quality"] == "partial")
        fail = sum(1 for i in items if i["quality"] == "fail")
        avg_keys = sum(i["key_ratio"] for i in items) / n if n else 0
        avg_ms = sum(i["total_ms"] for i in items) / n if n else 0
        per_file.append(
            {
                "source_file": sf,
                "questions": n,
                "retrieval_pct": round(100 * ret / n, 1) if n else 0,
                "good": good,
                "partial": partial,
                "fail": fail,
                "avg_key_ratio": round(avg_keys, 3),
                "avg_ms": round(avg_ms, 1),
                "score_pct": round(100 * (good + 0.5 * partial) / n, 1) if n else 0,
            }
        )

    total = len(results)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_questions": total,
        "total_files": len(per_file),
        "overall_retrieval_pct": round(
            100 * sum(1 for r in results if r["retrieval_hit"]) / total, 1
        )
        if total
        else 0,
        "overall_good": sum(1 for r in results if r["quality"] == "good"),
        "overall_partial": sum(1 for r in results if r["quality"] == "partial"),
        "overall_fail": sum(1 for r in results if r["quality"] == "fail"),
        "overall_score_pct": round(
            100
            * sum(
                1 if r["quality"] == "good" else 0.5 if r["quality"] == "partial" else 0
                for r in results
            )
            / total,
            1,
        )
        if total
        else 0,
        "avg_total_ms": round(sum(r["total_ms"] for r in results) / total, 1)
        if total
        else 0,
        "per_file": per_file,
        "results": results,
    }


def _load_questions(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("questions") or data.get("items") or []
    return data


def _save_output(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def run_benchmark(
    questions_path: str,
    output_path: str,
    resume: bool = False,
    limit: int | None = None,
) -> dict:
    questions = _load_questions(questions_path)
    if limit:
        questions = questions[:limit]

    done_keys: set[tuple] = set()
    existing_results: list[dict] = []

    if resume and os.path.isfile(output_path):
        prev = json.load(open(output_path, encoding="utf-8"))
        existing_results = prev.get("results") or []
        for r in existing_results:
            done_keys.add((r.get("source_file"), r.get("id")))

    bot = AdvancedChatbot(_CONFIG_PATH)
    if bot.config is None:
        raise RuntimeError("AdvancedChatbot не инициализировался")

    print(f"[benchmark] вопросов: {len(questions)}, уже готово: {len(done_keys)}")

    for idx, item in enumerate(questions, 1):
        key = (item.get("source_file"), item.get("id"))
        if key in done_keys:
            continue

        q = item.get("question", "")
        preview = _safe_console(q[:80])
        print(
            _safe_console(
                f"[{idx}/{len(questions)}] {item.get('source_file')} "
                f"#{item.get('id')}: {preview}..."
            ),
            flush=True,
        )
        t0 = time.perf_counter()
        try:
            answer = bot.generate_response(q)
        except Exception as exc:
            answer = f"ERROR: {exc}"
        total_ms = (time.perf_counter() - t0) * 1000
        llm_ms = getattr(bot, "last_llm_elapsed_ms", 0.0) or 0.0
        chunks = getattr(bot, "last_chunks", []) or []

        scored = _score_item(item, answer, chunks, total_ms, llm_ms)
        existing_results.append(scored)
        done_keys.add(key)

        payload = _aggregate(existing_results)
        _save_output(output_path, payload)
        print(
            f"  -> {scored['quality']} ret={scored['retrieval_hit']} "
            f"keys={scored['key_hits']}/{scored['key_total']} "
            f"{scored['total_ms']:.0f}ms"
        )

    final = _aggregate(existing_results)
    _save_output(output_path, final)
    print(f"[benchmark] сохранено: {output_path}")
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG benchmark runner")
    parser.add_argument("--questions", default=_DEFAULT_QUESTIONS)
    parser.add_argument("--output", default=_DEFAULT_OUTPUT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    summary = run_benchmark(
        args.questions, args.output, resume=args.resume, limit=args.limit
    )
    pf = summary.get("per_file") or []
    print(
        f"\nИтого: score={summary.get('overall_score_pct')}% "
        f"retrieval={summary.get('overall_retrieval_pct')}% "
        f"good/partial/fail="
        f"{summary.get('overall_good')}/"
        f"{summary.get('overall_partial')}/"
        f"{summary.get('overall_fail')}"
    )
    for row in pf:
        print(
            f"  {row['source_file'][:50]:50s} "
            f"score={row['score_pct']:5.1f}% ret={row['retrieval_pct']:5.1f}% "
            f"avg={row['avg_ms']:6.0f}ms"
        )


if __name__ == "__main__":
    main()

"""
Быстрый RAG-тест только retrieval (без LLM).
Критерий pass: expected source_file в top-8 чанков.

Запуск из back/chatbot:
  py tests/run_rag_retrieval_only.py
  py tests/run_rag_retrieval_only.py --questions tests/rag_3q_per_file.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

_TESTS = os.path.dirname(os.path.abspath(__file__))
_CHATBOT = os.path.normpath(os.path.join(_TESTS, ".."))
if _CHATBOT not in sys.path:
    sys.path.insert(0, _CHATBOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot.settings")

from api.chatbot_core.chatbot import (  # noqa: E402
    AdvancedChatbot,
    adjust_search_parameters,
    smart_search,
)

_CONFIG = os.path.normpath(os.path.join(_CHATBOT, "..", "project", "config.yaml"))
_DEFAULT_Q = os.path.join(_TESTS, "rag_3q_per_file.json")
_DEFAULT_OUT = os.path.join(_TESTS, "rag_retrieval_3q_results.json")


def _chunk_source(chunk: dict) -> str:
    meta = chunk.get("metadata") or {}
    return meta.get("source_file") or chunk.get("source_file") or ""


def _load_questions(path: str) -> list[dict]:
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("questions") or []
    return data


def run(questions_path: str, output_path: str) -> dict:
    questions = _load_questions(questions_path)
    bot = AdvancedChatbot(_CONFIG)
    if bot.config is None:
        raise RuntimeError("AdvancedChatbot не инициализировался")

    results = []
    for idx, item in enumerate(questions, 1):
        q = item.get("question", "")
        expected = item.get("source_file", "")
        t0 = time.perf_counter()
        qtype = bot.classifier.classify(q)
        params = adjust_search_parameters(qtype, bot.top_k, bot.threshold)
        emb = bot.embedder.encode(q)
        chunks = smart_search(
            bot.store,
            bot.product_detector,
            emb,
            q,
            params,
            qtype,
            hybrid_retriever=getattr(bot, "hybrid_retriever", None),
            use_hybrid=True,
        )
        ms = (time.perf_counter() - t0) * 1000
        top = [_chunk_source(c) for c in chunks[:8]]
        hit = expected in top
        rank = top.index(expected) + 1 if hit else None
        results.append({
            "source_file": expected,
            "id": item.get("id"),
            "question": q,
            "retrieval_hit": hit,
            "retrieval_rank": rank,
            "top_sources": top[:5],
            "total_ms": round(ms, 1),
            "pass": hit,
        })
        status = "PASS" if hit else "FAIL"
        print(f"[{idx}/{len(questions)}] {status} {expected} #{item.get('id')} rank={rank}")

    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    payload = {
        "total_questions": total,
        "passed": passed,
        "failed": total - passed,
        "pass_pct": round(100 * passed / total, 1) if total else 0,
        "results": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nRetrieval: {passed}/{total} ({payload['pass_pct']}%) -> {output_path}")
    return payload


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", default=_DEFAULT_Q)
    p.add_argument("--output", default=_DEFAULT_OUT)
    args = p.parse_args()
    run(args.questions, args.output)


if __name__ == "__main__":
    main()

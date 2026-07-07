# -*- coding: utf-8 -*-
"""
Бенчмарк 50 вопросов по РЭ/ОТ + сравнение с baseline и метрики RAG v2.

Запуск из back/chatbot:
  py tests/run_rag_benchmark_50_compare.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_CHATBOT_DIR = os.path.normpath(os.path.join(_TESTS_DIR, ".."))
if _CHATBOT_DIR not in sys.path:
    sys.path.insert(0, _CHATBOT_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot.settings")

from api.chatbot_core.chatbot import AdvancedChatbot  # noqa: E402
from api.chatbot_core.rag_sources import strip_inline_citations  # noqa: E402
from tests.run_rag_benchmark import (  # noqa: E402
    _CONFIG_PATH,
    _aggregate,
    _key_matches,
    _norm,
    _quality_label,
    _safe_console,
    _score_item,
    _chunk_source,
)

_QUESTIONS_PATH = os.path.join(_TESTS_DIR, "rag_benchmark_50_manual.json")
_OUTPUT_PATH = os.path.join(_TESTS_DIR, "rag_benchmark_50_after_rag_v2.json")
_BASELINE_PATH = os.path.join(_TESTS_DIR, "rag_benchmark_results_after_quality_fixes.json")
_CANVAS_DATA_PATH = os.path.join(_TESTS_DIR, "rag_benchmark_50_canvas_data.json")

_FALLBACK_MARKERS = (
    "не удалось найти информации",
    "временно недоступен",
    "произошла ошибка",
)


def _load_questions(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("questions") or []
    return data


def _baseline_map(path: str) -> dict[tuple[str, Any], dict]:
    if not os.path.isfile(path):
        return {}
    data = json.load(open(path, encoding="utf-8"))
    out: dict[tuple[str, Any], dict] = {}
    for row in data.get("results") or []:
        out[(row.get("source_file"), row.get("id"))] = row
    return out


def _extended_score(
    item: dict,
    answer: str,
    chunks: list[dict],
    total_ms: float,
    llm_ms: float,
    rag_sources: list[dict],
) -> dict[str, Any]:
    base = _score_item(item, answer, chunks, total_ms, llm_ms)
    raw = answer or ""
    cleaned = strip_inline_citations(raw)
    base["has_inline_citation"] = "[Документ:" in raw or "[документ:" in raw.lower()
    base["rag_sources_count"] = len(rag_sources or [])
    base["answer_cleaned_preview"] = cleaned[:500]
    base["rag_source_titles"] = [s.get("title") for s in (rag_sources or [])[:4]]
    return base


def _compare_row(current: dict, baseline: dict | None) -> dict[str, Any]:
    if not baseline:
        return {"delta_quality": None, "delta_key_ratio": None, "baseline_quality": None}
    q_order = {"fail": 0, "weak": 1, "partial": 2, "good": 3}
    cur_q = current.get("quality", "fail")
    base_q = baseline.get("quality", "fail")
    return {
        "baseline_quality": base_q,
        "delta_quality": q_order.get(cur_q, 0) - q_order.get(base_q, 0),
        "delta_key_ratio": round(
            float(current.get("key_ratio", 0)) - float(baseline.get("key_ratio", 0)),
            3,
        ),
        "baseline_retrieval_hit": baseline.get("retrieval_hit"),
    }


def _build_comparison_summary(
    results: list[dict],
    baseline_rows: dict[tuple[str, Any], dict],
) -> dict[str, Any]:
    agg = _aggregate(results)
    comparisons: list[dict] = []
    improved = regressed = same = 0
    for r in results:
        key = (r.get("source_file"), r.get("id"))
        base = baseline_rows.get(key)
        cmp = _compare_row(r, base)
        row = {**r, **cmp}
        comparisons.append(row)
        if base is None:
            continue
        dq = cmp.get("delta_quality")
        if dq is None:
            continue
        if dq > 0:
            improved += 1
        elif dq < 0:
            regressed += 1
        else:
            same += 1

    with_baseline = [c for c in comparisons if c.get("baseline_quality") is not None]
    baseline_score = 0.0
    if with_baseline:
        baseline_score = round(
            100
            * sum(
                1
                if c["baseline_quality"] == "good"
                else 0.5
                if c["baseline_quality"] == "partial"
                else 0
                for c in with_baseline
            )
            / len(with_baseline),
            1,
        )

    return {
        **agg,
        "label": "RAG v2 (multi-product + sources widget)",
        "baseline_label": "after_quality_fixes (subset)",
        "baseline_questions_matched": len(with_baseline),
        "baseline_score_pct": baseline_score,
        "delta_score_pct": round(float(agg.get("overall_score_pct", 0)) - baseline_score, 1)
        if with_baseline
        else None,
        "quality_improved": improved,
        "quality_regressed": regressed,
        "quality_same": same,
        "inline_citations_count": sum(1 for r in results if r.get("has_inline_citation")),
        "avg_rag_sources": round(
            sum(r.get("rag_sources_count", 0) for r in results) / len(results), 2
        )
        if results
        else 0,
        "results": comparisons,
    }


def _canvas_payload(summary: dict) -> dict[str, Any]:
    by_file = summary.get("per_file") or []
    quality_counts = Counter(r.get("quality") for r in summary.get("results") or [])
    baseline_map = {
        row["source_file"]: row
        for row in by_file
    }
    baseline_per_file = summary.get("baseline_per_file") or []

    return {
        "title": "RAG benchmark: 50 вопросов по РЭ/ОТ",
        "generated_at": summary.get("generated_at"),
        "current": {
            "score_pct": summary.get("overall_score_pct"),
            "retrieval_pct": summary.get("overall_retrieval_pct"),
            "good": summary.get("overall_good"),
            "partial": summary.get("overall_partial"),
            "fail": summary.get("overall_fail"),
            "avg_ms": summary.get("avg_total_ms"),
            "inline_citations": summary.get("inline_citations_count"),
            "avg_rag_sources": summary.get("avg_rag_sources"),
        },
        "baseline": {
            "score_pct": summary.get("baseline_score_pct"),
            "matched": summary.get("baseline_questions_matched"),
        },
        "delta_score_pct": summary.get("delta_score_pct"),
        "quality_shift": {
            "improved": summary.get("quality_improved"),
            "regressed": summary.get("quality_regressed"),
            "same": summary.get("quality_same"),
        },
        "quality_distribution": dict(quality_counts),
        "per_file": by_file,
        "worst": sorted(by_file, key=lambda x: x.get("score_pct", 0))[:5],
        "best": sorted(by_file, key=lambda x: -x.get("score_pct", 0))[:5],
    }


def run() -> dict[str, Any]:
    questions = _load_questions(_QUESTIONS_PATH)
    baseline_rows = _baseline_map(_BASELINE_PATH)

    bot = AdvancedChatbot(_CONFIG_PATH)
    if bot.config is None:
        raise RuntimeError("AdvancedChatbot не инициализировался")

    results: list[dict] = []
    print(f"[benchmark-50] вопросов: {len(questions)}")

    for idx, item in enumerate(questions, 1):
        q = item.get("question", "")
        print(
            _safe_console(f"[{idx}/{len(questions)}] {item.get('source_file')} #{item.get('id')}: {q[:70]}..."),
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
        rag_sources = getattr(bot, "last_rag_sources", []) or []

        scored = _extended_score(item, answer, chunks, total_ms, llm_ms, rag_sources)
        results.append(scored)
        print(
            f"  -> {scored['quality']} ret={scored['retrieval_hit']} "
            f"keys={scored['key_hits']}/{scored['key_total']} "
            f"sources={scored['rag_sources_count']} "
            f"inline={scored['has_inline_citation']} "
            f"{scored['total_ms']:.0f}ms"
        )

    summary = _build_comparison_summary(results, baseline_rows)

    # baseline per-file for same 50
    baseline_subset = [
        baseline_rows[(q["source_file"], q["id"])]
        for q in questions
        if (q["source_file"], q["id"]) in baseline_rows
    ]
    if baseline_subset:
        fake_agg = _aggregate(baseline_subset)
        summary["baseline_per_file"] = fake_agg.get("per_file")
        summary["baseline_overall"] = {
            k: fake_agg.get(k)
            for k in (
                "overall_score_pct",
                "overall_retrieval_pct",
                "overall_good",
                "overall_partial",
                "overall_fail",
                "avg_total_ms",
            )
        }

    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    canvas = _canvas_payload(summary)
    with open(_CANVAS_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(canvas, f, ensure_ascii=False, indent=2)

    print(f"\n[benchmark-50] сохранено: {_OUTPUT_PATH}")
    print(
        f"Score: {summary.get('overall_score_pct')}% "
        f"(baseline subset {summary.get('baseline_score_pct')}%, "
        f"delta {summary.get('delta_score_pct'):+}%)"
    )
    print(
        f"Retrieval: {summary.get('overall_retrieval_pct')}% | "
        f"inline citations: {summary.get('inline_citations_count')} | "
        f"avg sources: {summary.get('avg_rag_sources')}"
    )
    print(
        f"Shift: +{summary.get('quality_improved')} "
        f"/ -{summary.get('quality_regressed')} "
        f"/ ={summary.get('quality_same')}"
    )
    return summary


if __name__ == "__main__":
    run()

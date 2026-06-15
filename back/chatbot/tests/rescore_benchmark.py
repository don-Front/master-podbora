"""Пересчёт quality в сохранённом rag_*_benchmark_results.json без повторного LLM."""
from __future__ import annotations

import json
import os
import sys

import importlib.util

_TESTS = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "run_rag_benchmark", os.path.join(_TESTS, "run_rag_benchmark.py")
)
_rb = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(_rb)
_aggregate = _rb._aggregate
_quality_label = _rb._quality_label
_key_matches = _rb._key_matches
_norm = _rb._norm

_FALLBACK = (
    "не удалось найти информации",
    "временно недоступен",
    "произошла ошибка",
)


def rescore(path: str) -> dict:
    data = json.load(open(path, encoding="utf-8"))
    results = []
    for r in data.get("results") or []:
        answer = r.get("answer_preview") or ""
        keys = r.get("expected_keys") or []
        ans = _norm(answer)
        is_fallback = not answer.strip() or any(m in ans for m in _FALLBACK)
        key_hits = sum(1 for k in keys if _key_matches(k, answer))
        key_total = len(keys)
        key_ratio = key_hits / key_total if key_total else 0.0
        retrieval_hit = r.get("retrieval_hit", False)
        quality = _quality_label(
            retrieval_hit, key_ratio, is_fallback, key_hits=key_hits, key_total=key_total
        )
        nr = dict(r)
        nr["key_hits"] = key_hits
        nr["key_ratio"] = round(key_ratio, 3)
        nr["quality"] = quality
        results.append(nr)
    out = _aggregate(results)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


if __name__ == "__main__":
    p = os.path.join(_TESTS, "rag_3q_benchmark_results.json")
    s = rescore(p)
    print(
        f"Rescored: good={s['overall_good']} partial={s['overall_partial']} "
        f"fail={s['overall_fail']} score={s['overall_score_pct']}% "
        f"retrieval={s['overall_retrieval_pct']}%"
    )

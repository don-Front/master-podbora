"""
Сборка данных для canvas из rag_benchmark_results.json.
Запуск: py tests/build_benchmark_canvas_data.py
"""

from __future__ import annotations

import json
import os

_TESTS = os.path.dirname(os.path.abspath(__file__))
_RESULTS = os.path.join(_TESTS, "rag_benchmark_results.json")
_OUT = os.path.join(_TESTS, "rag_benchmark_canvas_data.json")


def main() -> None:
    if not os.path.isfile(_RESULTS):
        print(f"No results yet: {_RESULTS}")
        return
    data = json.load(open(_RESULTS, encoding="utf-8"))
    per_file = data.get("per_file") or []
    summary = {k: data[k] for k in data if k != "results"}
    out = {"summary": summary, "per_file": per_file}
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Canvas data: {len(per_file)} files, score={summary.get('overall_score_pct')}%")


if __name__ == "__main__":
    main()

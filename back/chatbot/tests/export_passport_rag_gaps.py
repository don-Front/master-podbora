# -*- coding: utf-8 -*-
"""Сводка пробелов RAG по всем passport-аудитам — база для улучшения."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_RESULTS_DIR = _TESTS_DIR / "passport_file_audit_results"
_GAPS_JSON = _TESTS_DIR / "passport_rag_gaps.json"
_GAPS_MD = _TESTS_DIR / "passport_rag_gaps.md"
_SUMMARY = _TESTS_DIR / "passport_batch_summary.json"


def _load_all_results() -> list[dict]:
    rows: list[dict] = []
    if not _RESULTS_DIR.is_dir():
        return rows
    for p in sorted(_RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            sf = data.get("source_file") or p.stem
            fi = data.get("file_index")
            for r in data.get("results") or []:
                r = dict(r)
                r.setdefault("source_file", sf)
                r.setdefault("file_index", fi)
                rows.append(r)
        except Exception:
            continue
    return rows


def build_gaps_export() -> dict:
    rows = _load_all_results()
    failures = [r for r in rows if r.get("judge_verdict") not in ("CORRECT", "PARTIAL")]
    partials = [r for r in rows if r.get("judge_verdict") == "PARTIAL"]

    by_file: dict[str, list] = defaultdict(list)
    by_bug: dict[str, list] = defaultdict(list)
    by_topic: dict[str, list] = defaultdict(list)
    retrieval_miss = [r for r in rows if not r.get("retrieval_hit")]

    for r in failures:
        sf = r.get("source_file") or "?"
        by_file[sf].append(r)
        bug = r.get("bug_type") or r.get("judge_verdict") or "unknown"
        by_bug[bug].append(r)
        by_topic[r.get("topic") or "—"].append(r)

    file_stats: list[dict] = []
    files_seen = sorted({r.get("source_file") for r in rows if r.get("source_file")})
    for sf in files_seen:
        fr = [x for x in rows if x.get("source_file") == sf]
        n = len(fr)
        if not n:
            continue
        ok = sum(1 for x in fr if x.get("judge_verdict") == "CORRECT")
        part = sum(1 for x in fr if x.get("judge_verdict") == "PARTIAL")
        bad = n - ok - part
        ret = sum(1 for x in fr if x.get("retrieval_hit"))
        file_stats.append(
            {
                "source_file": sf,
                "file_index": fr[0].get("file_index"),
                "questions": n,
                "correct": ok,
                "partial": part,
                "bad": bad,
                "accuracy_pct": round(100 * ok / n, 1),
                "retrieval_pct": round(100 * ret / n, 1),
                "top_bugs": Counter(
                    x.get("bug_type") for x in fr if x.get("judge_verdict") not in ("CORRECT", "PARTIAL")
                ).most_common(5),
            }
        )
    file_stats.sort(key=lambda x: (x.get("accuracy_pct") or 0, -(x.get("bad") or 0)))

    export = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_questions": len(rows),
        "total_failures": len(failures),
        "total_partial": len(partials),
        "retrieval_miss_count": len(retrieval_miss),
        "verdict_counts": dict(Counter(r.get("judge_verdict") for r in rows)),
        "bug_counts": dict(Counter(r.get("bug_type") for r in failures)),
        "worst_files": file_stats[:20],
        "best_files": list(reversed(file_stats[-10:])) if file_stats else [],
        "failures_by_bug": {
            k: [
                {
                    "source_file": x.get("source_file"),
                    "question": x.get("question"),
                    "verdict": x.get("judge_verdict"),
                    "bug_type": x.get("bug_type"),
                    "reason": x.get("judge_reason"),
                    "top_sources": x.get("top_sources"),
                    "answer_preview": (x.get("answer_preview") or "")[:400],
                }
                for x in v[:50]
            ]
            for k, v in sorted(by_bug.items(), key=lambda i: -len(i[1]))
        },
        "retrieval_misses_sample": [
            {
                "source_file": x.get("source_file"),
                "question": x.get("question"),
                "verdict": x.get("judge_verdict"),
                "top_sources": x.get("top_sources"),
            }
            for x in retrieval_miss[:100]
        ],
        "per_file_stats": file_stats,
    }
    return export


def _write_md(export: dict) -> None:
    lines = [
        "# База пробелов RAG (passport/)",
        "",
        f"Обновлено: {export.get('generated_at', '')[:19]}",
        f"Вопросов в базе: **{export.get('total_questions')}**",
        f"Провалов (не CORRECT/PARTIAL): **{export.get('total_failures')}**",
        f"Retrieval miss: **{export.get('retrieval_miss_count')}**",
        "",
        "## Вердикты",
        "",
    ]
    for k, v in sorted((export.get("verdict_counts") or {}).items(), key=lambda i: -i[1]):
        lines.append(f"- {k}: {v}")

    lines.extend(["", "## Типы багов (провалы)", ""])
    for k, v in sorted((export.get("bug_counts") or {}).items(), key=lambda i: -i[1]):
        lines.append(f"- `{k}`: {v}")

    lines.extend(["", "## Худшие файлы (accuracy)", "", "| Файл | CORRECT | Ret | Плохие |", "|------|---------|-----|--------|"])
    for f in export.get("worst_files") or []:
        lines.append(
            f"| `{f['source_file'][:55]}` | {f['correct']}/{f['questions']} ({f['accuracy_pct']}%) | "
            f"{f['retrieval_pct']}% | {f['bad']} |"
        )

    lines.extend(["", "## Лучшие файлы", "", "| Файл | CORRECT | Ret |", "|------|---------|-----|"])
    for f in export.get("best_files") or []:
        lines.append(f"| `{f['source_file'][:55]}` | {f['correct']}/{f['questions']} ({f['accuracy_pct']}%) | {f['retrieval_pct']}% |")

    lines.extend(
        [
            "",
            "Полные данные: `passport_rag_gaps.json`",
            "Сводка по файлам: `passport_batch_summary.json`",
            "Отчёты: `passport_file_audit_reports/`",
        ]
    )
    _GAPS_MD.write_text("\n".join(lines), encoding="utf-8")


def export_gaps() -> dict:
    export = build_gaps_export()
    _GAPS_JSON.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(export)
    return export


def main() -> None:
    p = argparse.ArgumentParser()
    p.parse_args()
    e = export_gaps()
    print(f"exported {_GAPS_JSON} failures={e.get('total_failures')} questions={e.get('total_questions')}")


if __name__ == "__main__":
    main()

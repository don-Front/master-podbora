# -*- coding: utf-8 -*-
"""Пакетный аудит passport/: генерация 50 вопросов + прогон API по всем файлам."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR.parent))

from tests.generate_passport_file_questions import _passport_files, generate_questions  # noqa: E402
from tests.run_passport_single_file_audit import (  # noqa: E402
    _DEFAULT_API,
    _QUESTIONS_DIR,
    _RESULTS_DIR,
    _REPORTS_DIR,
    _write_md_report,
    run_file_audit,
)

try:
    from tests.export_passport_rag_gaps import export_gaps  # noqa: E402
except ImportError:
    export_gaps = None  # type: ignore

_SUMMARY_PATH = _TESTS_DIR / "passport_batch_summary.json"


def _update_batch_summary(file_index: int, result: dict) -> None:
    files = _passport_files()
    summary: dict = {}
    if _SUMMARY_PATH.is_file():
        summary = json.loads(_SUMMARY_PATH.read_text(encoding="utf-8"))
    per_file = {r["file_index"]: r for r in summary.get("per_file", [])}
    per_file[file_index] = {
        "file_index": file_index,
        "source_file": result.get("source_file"),
        "questions": result.get("total_questions"),
        "accuracy_pct": result.get("accuracy_pct"),
        "partial_pct": result.get("partial_pct"),
        "bad_pct": result.get("bad_pct"),
        "retrieval_pct": (result.get("per_file") or [{}])[0].get("retrieval_pct"),
        "verdict_counts": result.get("verdict_counts"),
    }
    rows = [per_file[i] for i in sorted(per_file)]
    n = len(rows)
    acc = sum(r.get("accuracy_pct") or 0 for r in rows) / n if n else 0
    ret = sum(r.get("retrieval_pct") or 0 for r in rows) / n if n else 0
    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "files_total": len(files),
        "files_done": n,
        "avg_accuracy_pct": round(acc, 1),
        "avg_retrieval_pct": round(ret, 1),
        "per_file": rows,
    }
    _SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_readme(summary)


def _write_readme(summary: dict) -> None:
    lines = [
        "# Аудит RAG по документам `passport/`",
        "",
        f"Обновлено: {summary.get('updated_at', '')[:19]}",
        f"**Средняя точность (CORRECT):** {summary.get('avg_accuracy_pct')}%",
        f"**Средний retrieval:** {summary.get('avg_retrieval_pct')}%",
        f"**Файлов готово:** {summary.get('files_done')}/{summary.get('files_total')}",
        "",
        "| # | Файл | CORRECT | PARTIAL | Плохие | Ret | Отчёт |",
        "|---|------|---------|---------|--------|-----|-------|",
    ]
    for r in summary.get("per_file") or []:
        idx = r["file_index"] + 1
        sf = r.get("source_file", "")
        vc = r.get("verdict_counts") or {}
        correct = vc.get("CORRECT", 0)
        partial = vc.get("PARTIAL", 0)
        total = r.get("questions") or 0
        bad = total - correct - partial
        safe = sf.replace(" ", "%20")
        lines.append(
            f"| {idx} | `{sf[:50]}` | {correct}/{total} ({r.get('accuracy_pct')}%) | "
            f"{partial} | {bad} | {r.get('retrieval_pct')}% | "
            f"[{idx:02d}]({idx:02d}_{safe}.md) |"
        )
    lines.extend(
        [
            "",
            "Пакетный запуск:",
            "```bash",
            "cd back/chatbot",
            "py tests/run_passport_batch_audit.py --start-index 4 --questions 50",
            "```",
        ]
    )
    (_REPORTS_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _ensure_questions(file_index: int, count: int, force: bool = False) -> Path:
    import re

    files = _passport_files()
    sf = files[file_index]
    stem = re.sub(r"[^\w\-]+", "_", sf, flags=re.UNICODE).strip("_")[:40]
    out = _QUESTIONS_DIR / f"{file_index + 1:02d}_{stem}.json"
    _QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    if not force and out.is_file():
        data = json.loads(out.read_text(encoding="utf-8"))
        if len(data.get("questions") or []) >= count:
            return out
    payload = generate_questions(sf, count=count)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _ingest_existing_results() -> None:
    if not _RESULTS_DIR.is_dir():
        return
    for p in sorted(_RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            idx = data.get("file_index")
            if idx is None:
                continue
            _update_batch_summary(int(idx), data)
        except Exception:
            continue


def run_batch(
    start_index: int,
    end_index: int | None,
    questions: int,
    api_base: str,
    resume: bool,
    regen_questions: bool,
) -> None:
    files = _passport_files()
    end = (end_index if end_index is not None else len(files) - 1)
    _ingest_existing_results()
    for idx in range(start_index, end + 1):
        _ensure_questions(idx, questions, force=regen_questions)
        out_json = _RESULTS_DIR / f"{idx + 1:02d}_{files[idx]}.json"
        use_resume = resume and out_json.is_file()
        use_fresh = not use_resume
        if regen_questions:
            use_fresh = True
            use_resume = False
        result = run_file_audit(idx, api_base, fresh=use_fresh, resume=use_resume)
        _update_batch_summary(idx, result)
        if export_gaps:
            export_gaps()
        print(
            f"[batch] done #{idx + 1} acc={result.get('accuracy_pct')}% "
            f"ret={(result.get('per_file') or [{}])[0].get('retrieval_pct')}%"
        )

    # Дозаполнить файлы до start_index (если стартовали не с 0) — 50 вопросов на файл
    if start_index > 0:
        print(f"[batch] phase-2: files #1..#{start_index} with {questions} questions")
        for idx in range(0, start_index):
            _ensure_questions(idx, questions, force=regen_questions)
            out_json = _RESULTS_DIR / f"{idx + 1:02d}_{files[idx]}.json"
            prev = json.loads(out_json.read_text(encoding="utf-8")) if out_json.is_file() else {}
            need = (prev.get("total_questions") or 0) < questions
            use_resume = resume and out_json.is_file() and not need
            use_fresh = not use_resume or need
            if need and regen_questions:
                use_fresh = True
                use_resume = False
            result = run_file_audit(idx, api_base, fresh=use_fresh, resume=use_resume)
            _update_batch_summary(idx, result)
            if export_gaps:
                export_gaps()
            print(
                f"[batch] phase-2 done #{idx + 1} acc={result.get('accuracy_pct')}% "
                f"ret={(result.get('per_file') or [{}])[0].get('retrieval_pct')}%"
            )

    if export_gaps:
        export_gaps()
        print("[batch] gaps exported -> tests/passport_rag_gaps.json")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start-index", type=int, default=4)
    p.add_argument("--end-index", type=int, default=None)
    p.add_argument("--questions", type=int, default=50)
    p.add_argument("--api", default=_DEFAULT_API)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--regen-questions", action="store_true")
    args = p.parse_args()
    run_batch(
        args.start_index,
        args.end_index,
        args.questions,
        args.api.strip(),
        args.resume,
        args.regen_questions,
    )


if __name__ == "__main__":
    main()

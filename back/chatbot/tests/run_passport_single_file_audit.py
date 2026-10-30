# -*- coding: utf-8 -*-
"""Аудит RAG по одному файлу из passport/ — через prod API (по умолчанию 50 вопросов)."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_CHATBOT_DIR = _TESTS_DIR.parent
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

from tests.run_passport_rag_audit import (  # noqa: E402
    _DEFAULT_API,
    _aggregate,
    _api_ask,
    _api_create_chat,
    _judge_combined,
    _score_row,
)
from tests.run_rag_benchmark import _safe_console  # noqa: E402

_PASSPORT_DIR = _CHATBOT_DIR.parent / "project" / "data" / "documents" / "passport"
_FILES_LIST = _TESTS_DIR / "_passport_files_list.txt"
_QUESTIONS_DIR = _TESTS_DIR / "passport_file_questions"
_RESULTS_DIR = _TESTS_DIR / "passport_file_audit_results"
_REPORTS_DIR = _TESTS_DIR / "passport_file_audit_reports"


def _verdict_emoji(verdict: str) -> str:
    return {
        "CORRECT": "✅",
        "PARTIAL": "⚠️",
        "WRONG_TOPIC": "❌",
        "HALLUCINATION": "❌",
        "NO_ANSWER": "❌",
        "STUB_ONLY": "❌",
        "ERROR": "❌",
    }.get(verdict or "", "❓")


def _write_md_report(summary: dict) -> Path:
    """Сохранить краткий отчёт по файлу в markdown."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    file_index = summary.get("file_index", 0)
    source_file = summary.get("source_file") or "unknown"
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", source_file)
    md_path = _REPORTS_DIR / f"{file_index + 1:02d}_{safe_name}.md"

    vc = summary.get("verdict_counts") or {}
    per = (summary.get("per_file") or [{}])[0]
    lines = [
        f"# Аудит RAG: `{source_file}`",
        "",
        f"- **Продукт:** {summary.get('product') or '—'}",
        f"- **Дата:** {summary.get('generated_at', '')[:19]}",
        f"- **Вопросов:** {summary.get('total_questions', 0)}",
        "",
        "## Сводка",
        "",
        "| Метрика | Значение |",
        "|---------|----------|",
        f"| CORRECT | {vc.get('CORRECT', 0)} ({summary.get('accuracy_pct', 0)}%) |",
        f"| PARTIAL | {vc.get('PARTIAL', 0)} ({summary.get('partial_pct', 0)}%) |",
        f"| Плохие | {summary.get('bad_pct', 0)}% |",
        f"| Retrieval hit | {per.get('retrieval_pct', 0)}% |",
        "",
        "## Результаты по вопросам",
        "",
        "| # | Тема | Вердикт | Ret | Ключи | Вопрос |",
        "|---|------|---------|-----|-------|--------|",
    ]
    for r in summary.get("results") or []:
        q = (r.get("question") or "").replace("|", "/")[:80]
        lines.append(
            f"| {r.get('id')} | {r.get('topic', '')} | {_verdict_emoji(r.get('judge_verdict', ''))} "
            f"{r.get('judge_verdict', '')} | {'да' if r.get('retrieval_hit') else 'нет'} | "
            f"{r.get('key_hits', 0)}/{r.get('key_total', 0)} | {q} |"
        )

    failures = [r for r in (summary.get("results") or []) if r.get("judge_verdict") not in ("CORRECT", "PARTIAL")]
    if failures:
        lines.extend(["", "## Проблемные ответы (кратко)", ""])
        for r in failures:
            lines.append(f"### #{r.get('id')} — {r.get('topic')}")
            lines.append(f"- **Вопрос:** {r.get('question')}")
            lines.append(f"- **Вердикт:** {r.get('judge_verdict')} ({r.get('bug_type')})")
            lines.append(f"- **Причина:** {r.get('judge_reason')}")
            preview = (r.get("answer_preview") or "").replace("\n", " ")[:300]
            lines.append(f"- **Ответ:** {preview}")
            src = ", ".join(r.get("top_sources") or []) or "—"
            lines.append(f"- **Источники:** {src}")
            lines.append("")

    lines.append(f"\n---\n*JSON: `passport_file_audit_results/{file_index + 1:02d}_{source_file}.json`*\n")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def _regenerate_md_from_json(json_path: Path) -> Path | None:
    if not json_path.is_file():
        return None
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    return _write_md_report(summary)


def _passport_files() -> list[str]:
    if _FILES_LIST.is_file():
        return [ln.strip() for ln in _FILES_LIST.read_text(encoding="utf-8").splitlines() if ln.strip() and ln.strip() != ".gitkeep"]
    return sorted(p.name for p in _PASSPORT_DIR.iterdir() if p.is_file() and p.name != ".gitkeep")


def _questions_path(file_index: int) -> Path:
    files = _passport_files()
    if file_index < 0 or file_index >= len(files):
        raise SystemExit(f"file_index {file_index} вне диапазона 0..{len(files)-1}")
    stem = re.sub(r"[^\w\-]+", "_", files[file_index], flags=re.UNICODE).strip("_")[:40]
    numbered = _QUESTIONS_DIR / f"{file_index + 1:02d}_{stem}.json"
    if numbered.is_file():
        return numbered
  # fallback: match by source_file inside json files
    for p in sorted(_QUESTIONS_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("source_file") == files[file_index]:
            return p
    raise SystemExit(f"Нет файла вопросов для #{file_index + 1}: {files[file_index]}")


def run_file_audit(file_index: int, api_base: str, fresh: bool = True, resume: bool = False) -> dict:
    files = _passport_files()
    source_file = files[file_index]
    qpath = _questions_path(file_index)
    payload = json.loads(qpath.read_text(encoding="utf-8"))
    items = payload.get("questions") or []
    for it in items:
        it.setdefault("source_file", payload.get("source_file") or source_file)

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _RESULTS_DIR / f"{file_index + 1:02d}_{source_file}.json"
    if fresh and out_path.is_file():
        out_path.unlink()

    results: list[dict] = []
    done: set[tuple] = set()
    if resume and out_path.is_file():
        prev = json.loads(out_path.read_text(encoding="utf-8"))
        results = prev.get("results") or []
        for r in results:
            done.add((r.get("source_file"), r.get("id")))
    chat_id = _api_create_chat(api_base)
    print(f"[file-audit] #{file_index + 1}/{len(files)} {source_file}")
    print(f"[file-audit] questions={len(items)} api={api_base} chat_id={chat_id}")

    for idx, item in enumerate(items, 1):
        key = (item.get("source_file"), item.get("id"))
        if key in done:
            continue
        q = item.get("question", "")
        print(_safe_console(f"  [{idx}/{len(items)}] {q[:75]}..."), flush=True)
        try:
            answer, rag_sources, total_ms = _api_ask(api_base, chat_id, q)
        except Exception as exc:
            answer = f"ERROR: {exc}"
            rag_sources = []
            total_ms = 0.0
        judge = _judge_combined(None, item, answer, [], rag_sources)
        row = _score_row(item, answer, [], judge, total_ms, rag_sources)
        results.append(row)
        done.add(key)
        summary = _aggregate(results)
        summary["file_index"] = file_index
        summary["source_file"] = source_file
        summary["product"] = payload.get("product", "")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(
            f"    -> {row['judge_verdict']} ret={row['retrieval_hit']} "
            f"keys={row['key_hits']}/{row['key_total']} {row['total_ms']:.0f}ms"
        )
        time.sleep(0.3)

    final = _aggregate(results)
    final["file_index"] = file_index
    final["source_file"] = source_file
    final["product"] = payload.get("product", "")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    md_path = _write_md_report(final)
    print(f"[file-audit] saved {out_path}")
    print(f"[file-audit] report {md_path}")
    return final


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file-index", type=int, default=0, help="0-based индекс файла в passport/")
    p.add_argument("--api", default=_DEFAULT_API)
    p.add_argument("--no-fresh", action="store_true")
    p.add_argument("--resume", action="store_true", help="продолжить с существующего JSON")
    p.add_argument("--md-only", type=str, default=None, help="пересобрать .md из JSON-файла")
    args = p.parse_args()
    if args.md_only:
        path = Path(args.md_only)
        md = _regenerate_md_from_json(path)
        print(f"report: {md}")
        return
    s = run_file_audit(args.file_index, args.api.strip(), fresh=not args.no_fresh, resume=args.resume)
    vc = s.get("verdict_counts") or {}
    print(
        f"\n=== {s.get('source_file')} ===\n"
        f"CORRECT={vc.get('CORRECT',0)} PARTIAL={vc.get('PARTIAL',0)} "
        f"BAD={s.get('bad_pct')}% accuracy={s.get('accuracy_pct')}%"
    )


if __name__ == "__main__":
    main()

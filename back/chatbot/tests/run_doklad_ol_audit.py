# -*- coding: utf-8 -*-
"""
Аудит распознавания опросных листов из папки «Для доклада».

Для каждого PDF/DOCX:
1) OCR / извлечение текста
2) Эталон (AI-аудит): отдельный LLM-промпт с акцентом на полноту
3) Чат-бот: production run_pdf_order_pipeline
4) Сравнение полей SPEC_KEYS

Результаты: tests/doklad_ol_audit/
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TESTS_DIR = Path(__file__).resolve().parent
_CHATBOT_DIR = _TESTS_DIR.parent
if str(_CHATBOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CHATBOT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbot.settings")
import django  # noqa: E402

django.setup()

from api.pdf_order_analysis import (  # noqa: E402
    SPEC_KEYS,
    _merge_specs,
    _normalize_specs,
    _parse_json_from_llm,
    _postprocess_specs,
    attachment_to_text,
    extract_specs_heuristic,
    run_pdf_order_pipeline,
    trim_text_for_llm,
)
from api.services.order_specs_service import OrderSpecsService  # noqa: E402

NON_OL_EXCLUDED = frozenset({"перечень вопросов.docx"})
INITIAL_AUDIT_AVG_PCT = 84.6

DEFAULT_SOURCE = Path(
    r"\\192.168.1.198\Files\22.Служба развития\1. Для общего доступа"
    r"\МАСТЕР ПОДБОРА\Для доклада"
)
OUT_DIR = _TESTS_DIR / "doklad_ol_audit"
RESULTS_DIR = OUT_DIR / "results"
REPORT_MD = OUT_DIR / "DOKLAD_OL_AUDIT_REPORT.md"
SUMMARY_JSON = OUT_DIR / "summary.json"

FIELD_LABELS: dict[str, str] = {
    "medium": "Среда",
    "gas_type": "Тип газа",
    "duplication_type": "Дублирование",
    "flowMin": "Расход min",
    "flowMax": "Расход max",
    "flow_unit": "Ед. расхода",
    "pressureMin": "Давление min",
    "pressureMax": "Давление max",
    "pressure_unit": "Ед. давления",
    "tempMediumMin": "T среды min",
    "tempMediumMax": "T среды max",
    "tempAmbientMin": "T окруж. min",
    "tempAmbientMax": "T окруж. max",
    "temperature_unit": "Ед. температуры",
    "accuracy": "Точность",
    "diameter": "Диаметр (DN)",
}

NUMERIC_KEYS = frozenset(
    {
        "flowMin",
        "flowMax",
        "pressureMin",
        "pressureMax",
        "tempMediumMin",
        "tempMediumMax",
        "tempAmbientMin",
        "tempAmbientMax",
        "diameter",
    }
)

SKIP_SUFFIXES = {".md"}


def _is_empty(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    if isinstance(val, str):
        t = val.strip().lower()
        return t in ("", "null", "none", "не указано", "n/a", "-", "—")
    return False


def _norm_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    s = s.replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    return s


def _norm_medium(val: Any) -> str:
    s = _norm_str(val)
    if s in ("gas", "газ", "газовая", "газовый"):
        return "gas"
    if s in ("liquid", "жидкость", "жидк", "жидкостная", "жидкостный"):
        return "liquid"
    return s


def _norm_duplication(val: Any) -> str:
    if _is_empty(val):
        return ""
    s = _norm_str(val)
    mapping = {
        "none": "none",
        "нет": "none",
        "без дублирования": "none",
        "partial": "partial",
        "частичное": "partial",
        "частичное дублирование": "partial",
        "full": "full",
        "полное": "full",
        "полное дублирование": "full",
    }
    return mapping.get(s, s)


def _norm_temperature_unit(val: Any) -> str:
    s = _norm_str(val)
    return s.replace("с", "c").replace("°", "").strip()


def _numeric_pair_equivalent(ref_a: Any, ref_b: Any, bot_a: Any, bot_b: Any) -> bool:
    ra, rb = _to_float(ref_a), _to_float(ref_b)
    ba, bb = _to_float(bot_a), _to_float(bot_b)
    if None in (ra, rb, ba, bb):
        return False
    tol = max(0.05 * max(abs(ra), abs(rb), abs(ba), abs(bb)), 1.0)
    direct = abs(ra - ba) <= tol and abs(rb - bb) <= tol
    swapped = abs(ra - bb) <= tol and abs(rb - ba) <= tol
    return direct or swapped


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = str(val).strip().replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _values_match(key: str, ref: Any, bot: Any) -> bool:
    if _is_empty(ref) and _is_empty(bot):
        return True
    if key == "duplication_type" and _is_empty(ref) and _norm_duplication(bot) == "none":
        return True
    if _is_empty(ref) or _is_empty(bot):
        return False
    if key == "medium":
        return _norm_medium(ref) == _norm_medium(bot)
    if key == "duplication_type":
        return _norm_duplication(ref) == _norm_duplication(bot)
    if key == "temperature_unit":
        return _norm_temperature_unit(ref) == _norm_temperature_unit(bot)
    if key in NUMERIC_KEYS:
        rf, bf = _to_float(ref), _to_float(bot)
        if rf is None or bf is None:
            return _norm_str(ref) == _norm_str(bot)
        if key == "diameter":
            return abs(rf - bf) < 0.5
        rel = abs(rf - bf) / max(abs(rf), abs(bf), 1e-9)
        return abs(rf - bf) <= max(0.05 * max(abs(rf), abs(bf)), 1.0) or rel < 0.02
    rs, bs = _norm_str(ref), _norm_str(bot)
    if rs == bs:
        return True
    if key == "accuracy":
        rn = rs.replace("%", "").replace(",", ".").strip()
        bn = bs.replace("%", "").replace(",", ".").strip()
        return rn == bn or rs.replace("%", "") == bs.replace("%", "")
    return rs in bs or bs in rs


def _field_filled(key: str, val: Any) -> bool:
    if key == "duplication_type" and _norm_duplication(val) == "none":
        return False
    return not _is_empty(val)


def _compare_specs(reference: dict[str, Any], bot: dict[str, Any]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    ref_filled = 0
    matched = 0
    mismatches = 0
    bot_missing = 0
    bot_extra = 0

    for key in SPEC_KEYS:
        ref_val = reference.get(key)
        bot_val = bot.get(key)
        ref_has = _field_filled(key, ref_val)
        bot_has = _field_filled(key, bot_val)
        if ref_has:
            ref_filled += 1
        if ref_has and bot_has:
            ok = _values_match(key, ref_val, bot_val)
            status = "match" if ok else "wrong"
            if ok:
                matched += 1
            else:
                mismatches += 1
        elif ref_has and not bot_has:
            status = "bot_missing"
            bot_missing += 1
        elif not ref_has and bot_has:
            status = "bot_extra"
            bot_extra += 1
        else:
            status = "both_empty"

        fields.append(
            {
                "key": key,
                "label": FIELD_LABELS.get(key, key),
                "status": status,
                "reference": ref_val,
                "bot": bot_val,
            }
        )

    if _numeric_pair_equivalent(
        reference.get("flowMin"),
        reference.get("flowMax"),
        bot.get("flowMin"),
        bot.get("flowMax"),
    ):
        for item in fields:
            if item["key"] in ("flowMin", "flowMax") and item["status"] == "wrong":
                item["status"] = "match"
        matched = sum(1 for item in fields if item["status"] == "match")
        mismatches = sum(1 for item in fields if item["status"] == "wrong")

    accuracy_pct = round(100 * matched / ref_filled, 1) if ref_filled else 100.0
    return {
        "fields": fields,
        "ref_filled": ref_filled,
        "matched": matched,
        "mismatches": mismatches,
        "bot_missing": bot_missing,
        "bot_extra": bot_extra,
        "accuracy_pct": accuracy_pct,
    }


def _build_audit_reference_prompt(document_text: str) -> tuple[str, str]:
    """Отдельный промпт для эталонного AI-разбора (более строгий к полноте)."""
    llm_input = trim_text_for_llm(document_text)
    user_block = llm_input if llm_input.strip() else "(текст пустой)"
    schema_hint = {k: None for k in SPEC_KEYS}
    system = (
        "Ты эксперт по опросным листам Turbo-Don. Твоя задача — максимально полно "
        "извлечь технические параметры расходомера из текста. "
        "Ответ — только один JSON без markdown. "
        f"Ключи строго: {', '.join(SPEC_KEYS)}. "
        "Читай таблицы, примечания, шапку и все варианты исполнения. "
        "Если параметр явно указан — обязательно заполни. Если нет — null. "
        "Не выдумывай значения. medium: gas/liquid/unknown. "
        "duplication_type: none/partial/full или null."
    )
    user = (
        "Проанализируй опросный лист как эталон для аудита качества чат-бота. "
        "Верни JSON по схеме:\n"
        f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
        f"Текст документа:\n---\n{user_block}\n---"
    )
    return system, user


def _extract_reference_specs(ocr_text: str, llm) -> tuple[dict[str, Any], str, float]:
    from api.chatbot_core.llm_client import LLMClient
    from api.pdf_order_analysis import _parse_specs_pairs_from_llm

    heuristic = extract_specs_heuristic(ocr_text)
    system_content, user_content = _build_audit_reference_prompt(ocr_text)
    t0 = time.perf_counter()
    create_kwargs: dict[str, Any] = {
        "model": llm.model,
        "temperature": 0.0,
        "max_tokens": min(1200, getattr(llm, "max_tokens", 1200)),
        "timeout": getattr(llm, "timeout", 180),
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
    }
    raw = ""
    data: dict[str, Any] = {}
    try:
        resp = llm.client.chat.completions.create(**create_kwargs)
        msg = resp.choices[0].message
        raw = LLMClient._extract_assistant_text(msg)
        if not raw.strip() and getattr(msg, "reasoning_content", None):
            raw = str(msg.reasoning_content or "").strip()
        try:
            data = _parse_json_from_llm(raw)
        except Exception:
            data = _parse_specs_pairs_from_llm(raw) or {}
        specs = _merge_specs(data, heuristic)
        specs = _postprocess_specs(specs, ocr_text)
        specs = _normalize_specs(specs)
        return specs, raw, round((time.perf_counter() - t0) * 1000, 1)
    except Exception as exc:
        specs = _normalize_specs(heuristic)
        return specs, f"[audit-llm-error] {exc}\n{raw}", round((time.perf_counter() - t0) * 1000, 1)


def _list_survey_files(source: Path) -> list[Path]:
    files: list[Path] = []
    if not source.exists():
        raise FileNotFoundError(f"Папка недоступна: {source}")
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".pdf", ".docx", ".doc"}:
            files.append(path)
    return files


def _safe_slug(rel: str) -> str:
    slug = re.sub(r'[<>:"/\\|?*]', "_", rel)
    return slug[:180] if len(slug) > 180 else slug


def _audit_one_file(path: Path, source_root: Path, service: OrderSpecsService, *, force: bool) -> dict[str, Any]:
    rel = str(path.relative_to(source_root))
    slug = _safe_slug(rel)
    out_path = RESULTS_DIR / f"{slug}.json"
    if out_path.is_file() and not force:
        with open(out_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    t0 = time.perf_counter()
    result: dict[str, Any] = {
        "file": rel,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        ocr_text, text_source = attachment_to_text(str(path))
        result["text_source"] = text_source
        result["ocr_chars"] = len(ocr_text or "")
        result["ocr_preview"] = (ocr_text or "")[:1500]
    except Exception as exc:
        result["error"] = f"text_extract: {exc}"
        result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        return result

    bot_specs, bot_ocr, bot_err, bot_llm_raw, bot_timing = run_pdf_order_pipeline(
        str(path), service.llm, skip_cache=force
    )
    ref_specs, ref_llm_raw, ref_llm_ms = _extract_reference_specs(bot_ocr or ocr_text, service.llm)
    heuristic = extract_specs_heuristic(bot_ocr or ocr_text)

    comparison = _compare_specs(ref_specs, bot_specs)
    result.update(
        {
            "bot_specs": bot_specs,
            "reference_specs": ref_specs,
            "heuristic_specs": heuristic,
            "comparison": comparison,
            "bot_error": bot_err,
            "bot_timing": bot_timing,
            "ref_llm_ms": ref_llm_ms,
            "bot_llm_raw_preview": (bot_llm_raw or "")[:800],
            "ref_llm_raw_preview": (ref_llm_raw or "")[:800],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    )
    if bot_err:
        result["pipeline_error"] = bot_err
    if result["ocr_chars"] < 200:
        result["warning"] = "low_ocr_chars"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    return result


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    ok_files = [
        r
        for r in results
        if not r.get("error")
        and not r.get("pipeline_error")
        and r.get("file") not in NON_OL_EXCLUDED
    ]
    accs = [r.get("comparison", {}).get("accuracy_pct", 0) for r in ok_files if r.get("comparison")]
    field_stats: dict[str, dict[str, int]] = {k: {"wrong": 0, "bot_missing": 0, "bot_extra": 0, "checked": 0} for k in SPEC_KEYS}

    for r in ok_files:
        for f in r.get("comparison", {}).get("fields", []):
            key = f.get("key")
            if key not in field_stats:
                continue
            if f.get("status") in ("wrong", "bot_missing", "bot_extra"):
                field_stats[key][f["status"]] += 1
            if f.get("status") in ("match", "wrong", "bot_missing"):
                field_stats[key]["checked"] += 1

    low_ocr = [r["file"] for r in results if (r.get("ocr_chars") or 0) < 200]
    worst = sorted(ok_files, key=lambda x: x.get("comparison", {}).get("accuracy_pct", 100))[:15]

    avg = round(sum(accs) / len(accs), 1) if accs else 0
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_files": total,
        "processed_ok": len(ok_files),
        "excluded_non_ol": sorted(NON_OL_EXCLUDED),
        "initial_audit_avg_pct": INITIAL_AUDIT_AVG_PCT,
        "delta_vs_initial_pct": round(avg - INITIAL_AUDIT_AVG_PCT, 1),
        "avg_accuracy_pct": avg,
        "median_accuracy_pct": sorted(accs)[len(accs) // 2] if accs else 0,
        "low_ocr_files": low_ocr,
        "field_problem_stats": field_stats,
        "worst_files": [
            {
                "file": w["file"],
                "accuracy_pct": w.get("comparison", {}).get("accuracy_pct"),
                "mismatches": w.get("comparison", {}).get("mismatches"),
                "bot_missing": w.get("comparison", {}).get("bot_missing"),
            }
            for w in worst
        ],
        "files": [
            {
                "file": r.get("file"),
                "accuracy_pct": r.get("comparison", {}).get("accuracy_pct"),
                "ocr_chars": r.get("ocr_chars"),
                "error": r.get("error") or r.get("pipeline_error"),
                "warning": r.get("warning"),
            }
            for r in results
        ],
    }


def _write_md_report(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        "# Аудит распознавания опросных листов (папка «Для доклада»)",
        "",
        f"**Дата:** {summary.get('generated_at', '')[:19]} UTC",
        f"**Файлов:** {summary.get('total_files', 0)}",
        f"**Успешно обработано:** {summary.get('processed_ok', 0)}",
        f"**Средняя точность полей (бот vs AI-эталон):** {summary.get('avg_accuracy_pct', 0)}%",
        f"**Медиана точности:** {summary.get('median_accuracy_pct', 0)}%",
        "",
        "## Сводка по проблемным полям",
        "",
        "| Поле | Ошибки значения | Не извлёк бот | Лишнее у бота |",
        "|------|-----------------|---------------|---------------|",
    ]
    for key in SPEC_KEYS:
        st = summary.get("field_problem_stats", {}).get(key, {})
        lines.append(
            f"| {FIELD_LABELS.get(key, key)} (`{key}`) | {st.get('wrong', 0)} | "
            f"{st.get('bot_missing', 0)} | {st.get('bot_extra', 0)} |"
        )

    lines.extend(["", "## Худшие файлы", ""])
    for w in summary.get("worst_files") or []:
        lines.append(
            f"- `{w.get('file')}` — точность {w.get('accuracy_pct')}%, "
            f"ошибок {w.get('mismatches')}, пропусков {w.get('bot_missing')}"
        )

    if summary.get("low_ocr_files"):
        lines.extend(["", "## Плохой OCR (< 200 символов)", ""])
        for name in summary["low_ocr_files"]:
            lines.append(f"- `{name}`")

    lines.extend(["", "## Детали по файлам", ""])
    for r in sorted(results, key=lambda x: x.get("comparison", {}).get("accuracy_pct", 100)):
        comp = r.get("comparison") or {}
        lines.append(f"### `{r.get('file')}`")
        lines.append("")
        lines.append(
            f"- OCR: {r.get('ocr_chars', 0)} симв. ({r.get('text_source', '?')}), "
            f"точность {comp.get('accuracy_pct', '—')}%"
        )
        if r.get("error") or r.get("pipeline_error"):
            lines.append(f"- **Ошибка пайплайна:** {r.get('error') or r.get('pipeline_error')}")
        if r.get("warning"):
            lines.append(f"- **Предупреждение:** {r.get('warning')}")

        problems = [
            f for f in comp.get("fields", [])
            if f.get("status") in ("wrong", "bot_missing", "bot_extra")
        ]
        if problems:
            lines.append("- **Расхождения:**")
            for p in problems:
                lines.append(
                    f"  - `{p['key']}` ({p['label']}): {p['status']} — "
                    f"эталон={p.get('reference')!r}, бот={p.get('bot')!r}"
                )
        else:
            lines.append("- Расхождений с эталоном нет (по заполненным полям).")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "### Как читать отчёт",
            "",
            "- **Эталон** — отдельный AI-разбор того же OCR-текста (аудит-промпт + эвристики).",
            "- **Бот** — production `run_pdf_order_pipeline` (как в чате при загрузке PDF).",
            "- `bot_missing` — бот не извлёк параметр, эталон нашёл.",
            "- `wrong` — оба извлекли, но значения расходятся.",
            "- `bot_extra` — бот заполнил поле, эталон считает пустым (возможная галлюцинация).",
            "",
            "JSON по файлам: `tests/doklad_ol_audit/results/`",
        ]
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Аудит опросных листов из «Для доклада»")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--limit", type=int, default=0, help="Обработать только N файлов")
    parser.add_argument("--force", action="store_true", help="Перезаписать существующие JSON")
    parser.add_argument("--file", type=str, default="", help="Только один относительный путь")
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="Пересчитать summary.json из results/*.json без прогона",
    )
    args = parser.parse_args()

    if args.metrics_only:
        results = []
        for path in sorted(RESULTS_DIR.glob("*.json")):
            with open(path, "r", encoding="utf-8") as fh:
                results.append(json.load(fh))
        summary = _aggregate(results)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(SUMMARY_JSON, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print(
            f"[doklad-audit] metrics: avg={summary['avg_accuracy_pct']}% "
            f"delta_vs_initial={summary['delta_vs_initial_pct']:+.1f}pp "
            f"files={summary['processed_ok']}",
            flush=True,
        )
        return 0

    source = args.source
    files = _list_survey_files(source)
    if args.file:
        files = [p for p in files if str(p.relative_to(source)) == args.file or args.file in str(p)]
    if args.limit > 0:
        files = files[: args.limit]

    print(f"[doklad-audit] файлов: {len(files)} из {source}", flush=True)
    service = OrderSpecsService()
    results: list[dict[str, Any]] = []

    for idx, path in enumerate(files, 1):
        rel = path.relative_to(source)
        print(f"[doklad-audit] ({idx}/{len(files)}) {rel}", flush=True)
        try:
            row = _audit_one_file(path, source, service, force=args.force)
        except Exception as exc:
            row = {"file": str(rel), "error": str(exc)}
        acc = row.get("comparison", {}).get("accuracy_pct")
        print(f"  -> accuracy={acc}% ocr={row.get('ocr_chars', 0)}", flush=True)
        results.append(row)

    summary = _aggregate(results)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_JSON, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    _write_md_report(summary, results)
    print(f"[doklad-audit] summary: {SUMMARY_JSON}", flush=True)
    print(f"[doklad-audit] report: {REPORT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

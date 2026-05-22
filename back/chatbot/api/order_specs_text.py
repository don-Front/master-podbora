# -*- coding: utf-8 -*-
"""Извлечение параметров расходомера из свободного текста пользователя."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Tuple

from .chatbot_core.llm_client import LLMClient
from .order_specs_helpers import (
    FIELD_LABELS,
    _format_spec_display_value,
    is_value_missing,
    merge_draft,
)
from .pdf_order_analysis import (
    SPEC_KEYS,
    _merge_specs,
    _normalize_specs,
    _parse_json_from_llm,
    _postprocess_specs,
    extract_specs_heuristic,
    normalize_accuracy_value,
)

logger = logging.getLogger(__name__)


TEXT_ORDER_SPECS_STATE = "order_specs_text_clarify"


_TEXT_INTENT_RE = re.compile(
    r"(?i)(подобр|нуж(?:ен|на|но)|ищу|требуется|расходомер|оборудован|прибор|"
    r"\bDN\s*\d|\bДУ\s*\d|диаметр|расход|давлен|мпа|бар|точност|природн\w*\s+газ|"
    r"\bгаз\b|жидкост)",
)


def looks_like_order_specs_request(text: str) -> bool:
    """Достаточно осторожный детектор: не перехватываем обычные вопросы без параметров/интента."""
    t = (text or "").strip()
    if len(t) < 10:
        return False
    low = t.lower()
    has_intent = any(x in low for x in ("подобр", "нуж", "ищу", "требуется"))
    has_equipment = any(x in low for x in ("оборудован", "прибор", "расходомер"))
    markers = (
        "dn",
        "ду",
        "диаметр",
        "расход",
        "давлен",
        "мпа",
        "точност",
        "температур",
        "газ",
        "жидк",
    )
    param_count = sum(1 for x in markers if x in low)
    has_number = bool(re.search(r"\d", t))
    return bool(
        _TEXT_INTENT_RE.search(t)
        and (
            (has_intent and (has_equipment or param_count > 0))
            or (has_equipment and has_number and param_count >= 1)
            or (has_number and param_count >= 3)
        )
    )


def _parse_num(raw: str) -> float | None:
    s = (raw or "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        x = float(m.group(0))
    except ValueError:
        return None
    return int(x) if abs(x - int(x)) < 1e-9 else x


def _num_to_int_if_possible(x: float | int | None) -> float | int | None:
    if x is None:
        return None
    return int(x) if abs(float(x) - int(float(x))) < 1e-9 else x


def _extract_range(text: str, pattern: str) -> tuple[float | int | None, float | int | None]:
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None, None
    a = _parse_num(m.group(1))
    b = _parse_num(m.group(2))
    if a is None or b is None:
        return None, None
    return _num_to_int_if_possible(min(a, b)), _num_to_int_if_possible(max(a, b))


def extract_specs_from_short_text(text: str) -> Dict[str, Any]:
    """Быстрые правила для популярных формулировок в чате; LLM остаётся основным источником."""
    raw = text or ""
    low = raw.lower()
    out: Dict[str, Any] = {k: None for k in SPEC_KEYS}

    if "природ" in low and "газ" in low:
        out["medium"] = "gas"
        out["gas_type"] = "природный газ"
    elif re.search(r"\bгаз\b", low) and "жидк" not in low:
        out["medium"] = "gas"
    elif "жидк" in low:
        out["medium"] = "liquid"
        out["gas_type"] = "жидкость"

    m = re.search(r"(?:\bDN|\bДУ|\bDy|диаметр|ду)\s*[-:=]?\s*(\d{2,4})", raw, re.IGNORECASE)
    if m:
        out["diameter"] = int(m.group(1))

    flow_min, flow_max = _extract_range(
        raw,
        r"(?:расход|q(?:min|max)?)[^\d-]{0,50}(-?\d+(?:[.,]\d+)?)\s*(?:-|–|—|до|\.{2,}|/)\s*(-?\d+(?:[.,]\d+)?)",
    )
    if flow_min is not None and flow_max is not None:
        out["flowMin"] = flow_min
        out["flowMax"] = flow_max
        if re.search(r"(ст\.?\s*)?м\s*[³3]\s*/?\s*ч|нм\s*[³3]\s*/?\s*ч", low):
            out["flow_unit"] = "ст.м³/ч"

    p_min, p_max = _extract_range(
        raw,
        r"(?:давлен|pressure|p)[^\d-]{0,50}(-?\d+(?:[.,]\d+)?)\s*(?:-|–|—|до|\.{2,}|/)\s*(-?\d+(?:[.,]\d+)?)",
    )
    if p_min is not None and p_max is not None:
        out["pressureMin"] = p_min
        out["pressureMax"] = p_max
    else:
        m = re.search(r"(?:давлен|pressure|p)[^\d-]{0,50}(-?\d+(?:[.,]\d+)?)", raw, re.IGNORECASE)
        if m:
            out["pressureMax"] = _parse_num(m.group(1))
    if out.get("pressureMax") is not None:
        if "мпа" in low or "mpa" in low:
            out["pressure_unit"] = "МПа"
        elif "бар" in low or "bar" in low:
            out["pressure_unit"] = "бар"
        elif "кпа" in low or "kpa" in low:
            out["pressure_unit"] = "кПа"

    tm_min, tm_max = _extract_range(
        raw,
        r"(?:температур\w*\s+(?:рабоч\w*\s+)?(?:сред\w*|измеряем\w*\s+сред\w*)|среда)[^\d-]{0,60}"
        r"(-?\d+(?:[.,]\d+)?)\s*(?:-|–|—|до|\+|\.{2,}|/)\s*(\+?-?\d+(?:[.,]\d+)?)",
    )
    if tm_min is not None and tm_max is not None:
        out["tempMediumMin"] = tm_min
        out["tempMediumMax"] = tm_max

    ta_min, ta_max = _extract_range(
        raw,
        r"(?:окружающ\w*|окр\.\s*сред\w*|ambient)[^\d-]{0,60}"
        r"(-?\d+(?:[.,]\d+)?)\s*(?:-|–|—|до|\+|\.{2,}|/)\s*(\+?-?\d+(?:[.,]\d+)?)",
    )
    if ta_min is not None and ta_max is not None:
        out["tempAmbientMin"] = ta_min
        out["tempAmbientMax"] = ta_max

    if any(out.get(k) is not None for k in ("tempMediumMin", "tempAmbientMin")):
        out["temperature_unit"] = "°C"

    m = re.search(
        r"(?:точност\w*|класс\s+точности)[^\dА-ЯA-Z]{0,30}([А-ЯA-Z]|\d+(?:[.,]\d+)?\s*%?)",
        raw,
        re.IGNORECASE,
    )
    if m:
        out["accuracy"] = normalize_accuracy_value(m.group(1))

    return _normalize_specs(out)


def _llm_extract_text_specs(text: str, llm, base_draft: Dict[str, Any] | None = None) -> tuple[Dict[str, Any], str, float]:
    base = merge_draft(base_draft or {})
    schema_hint = {k: None for k in SPEC_KEYS}
    system_content = (
        "Ты извлекаешь параметры расходомера из сообщения пользователя. "
        "Ответ — только один JSON-объект без markdown. "
        f"Ключи строго такие: {', '.join(SPEC_KEYS)}. "
        'medium: "gas", "liquid" или "unknown". '
        "gas_type — тип среды (например, природный газ). "
        "flowMin/flowMax — расход, pressureMin/pressureMax — давление, "
        "tempMediumMin/Max — температура измеряемой среды, "
        "tempAmbientMin/Max — температура окружающей среды. "
        "Если значения нет в сообщении и его нет в текущем черновике — null. "
        "Если пользователь указал новое значение для поля — замени им значение черновика. "
        "Не придумывай отсутствующие параметры."
    )
    user_content = (
        "Текущий черновик JSON:\n"
        f"{json.dumps(base, ensure_ascii=False)}\n\n"
        "Пример структуры ответа:\n"
        f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
        "Новое сообщение пользователя:\n"
        f"{text}"
    )

    max_tokens = min(1024, getattr(llm, "max_tokens", 1024))
    timeout = getattr(llm, "timeout", 120)
    t0 = time.perf_counter()
    response = llm.client.chat.completions.create(
        model=llm.model,
        temperature=0.1,
        max_tokens=max_tokens,
        timeout=timeout,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    if not response or not response.choices:
        raise RuntimeError("пустой ответ LLM")
    raw = LLMClient._extract_assistant_text(response.choices[0].message)
    data = _parse_json_from_llm(raw)
    return data, raw, elapsed_ms


def extract_order_specs_from_text(
    text: str,
    llm=None,
    base_draft: Dict[str, Any] | None = None,
) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
    """LLM + эвристики + существующий черновик. Возвращает (draft, raw_llm, error, timing)."""
    base = merge_draft(base_draft or {})
    quick = _merge_specs(extract_specs_from_short_text(text), extract_specs_heuristic(text))
    raw = ""
    err = ""
    llm_ms = 0.0
    llm_data: Dict[str, Any] = {}

    if llm is not None:
        try:
            llm_data, raw, llm_ms = _llm_extract_text_specs(text, llm, base)
        except Exception as exc:
            err = str(exc)[:500]
            logger.warning("LM Studio text specs extraction failed: %s", exc)

    merged = _merge_specs(llm_data, quick)
    merged = _merge_specs(merged, base)
    merged = _postprocess_specs(merged, text)
    return merge_draft(merged), raw, err, {"llm_ms": llm_ms}


def _field_line(key: str, value: Any, draft: Dict[str, Any] | None = None) -> str:
    label = FIELD_LABELS.get(key, key)
    display = _format_spec_display_value(key, value, draft)
    return f"- {label}: {display}"


# Короткие подсказки для недостающих полей — см. _missing_field_rows

_UNIT_ONLY_KEYS = frozenset({"flow_unit", "pressure_unit", "temperature_unit"})


def _format_value_range(d: Dict[str, Any], min_key: str, max_key: str) -> str:
    lo, hi = d.get(min_key), d.get(max_key)
    has_lo = not is_value_missing(min_key, lo)
    has_hi = not is_value_missing(max_key, hi)
    if has_lo and has_hi:
        return f"{lo}–{hi}"
    if has_lo:
        return str(lo)
    if has_hi:
        return str(hi)
    return ""


def _missing_field_rows(missing: List[str], draft: Dict[str, Any] | None = None) -> List[Dict[str, str]]:
    """Строки недостающих параметров: подпись + пример значения."""
    missing_set = set(missing)
    d = merge_draft(draft or {})
    rows: List[Dict[str, str]] = []
    covered: set[str] = set()

    def add_row(keys: tuple[str, ...], label: str, example: str) -> None:
        group_missing = [k for k in keys if k in missing_set]
        if not group_missing:
            return
        covered.update(group_missing)
        rows.append({"label": label, "example": example})

    def add_group(
        keys: tuple[str, ...],
        value_keys: tuple[str, ...],
        unit_key: str | None,
        group_label: str,
        group_example: str,
        unit_label: str,
        unit_example: str,
    ) -> None:
        group_missing = [k for k in keys if k in missing_set]
        if not group_missing:
            return
        covered.update(group_missing)
        if any(k in missing_set for k in value_keys):
            rows.append({"label": group_label, "example": group_example})
        elif unit_key and unit_key in missing_set:
            ctx = _format_value_range(d, value_keys[0], value_keys[1]) if len(value_keys) >= 2 else ""
            label = f"{unit_label} ({ctx})" if ctx else unit_label
            rows.append({"label": label, "example": unit_example})

    add_row(("medium",), "Среда", "газ / жидкость")
    add_row(("gas_type",), "Тип среды", "природный газ")
    add_group(
        ("flowMin", "flowMax", "flow_unit"),
        ("flowMin", "flowMax"),
        "flow_unit",
        "Расход (мин. и макс.)",
        "мин. 3100 — макс. 244000, ст.м³/ч",
        "В каких единицах измеряется расход",
        "ст.м³/ч, м³/ч",
    )
    add_group(
        ("pressureMin", "pressureMax", "pressure_unit"),
        ("pressureMin", "pressureMax"),
        "pressure_unit",
        "Давление (мин. и макс.)",
        "3,95–7,35 МПа",
        "В каких единицах измеряется давление",
        "бар, МПа, кПа",
    )
    add_group(
        ("tempMediumMin", "tempMediumMax"),
        ("tempMediumMin", "tempMediumMax"),
        None,
        "Температура рабочей среды",
        "-10...+30 °C",
        "Температура рабочей среды",
        "-10...+30 °C",
    )
    add_group(
        ("tempAmbientMin", "tempAmbientMax", "temperature_unit"),
        ("tempAmbientMin", "tempAmbientMax"),
        "temperature_unit",
        "Температура окружающей среды",
        "-40...+38 °C",
        "В каких единицах указана температура",
        "°C",
    )
    add_row(("accuracy",), "Точность", "1%")
    add_row(("diameter",), "Диаметр (DN)", "300 мм")

    for key in missing:
        if key in covered:
            continue
        label = FIELD_LABELS.get(key, key)
        rows.append({"label": label, "example": ""})

    return rows


def _clarify_missing_hint(missing: List[str], draft: Dict[str, Any]) -> str:
    missing_set = set(missing)
    if not missing_set:
        return "Укажите недостающие параметры."
    if missing_set.issubset(_UNIT_ONLY_KEYS):
        return (
            "Числовые значения уже определены. Уточните, пожалуйста, "
            "в каких единицах они указаны (ниже — только примеры):"
        )
    unit_keys = missing_set & _UNIT_ONLY_KEYS
    if unit_keys:
        return (
            "Укажите недостающие параметры. "
            "Если числа уже указаны выше — уточните единицы измерения (ниже — только примеры):"
        )
    return "Укажите недостающие параметры. Ниже — только примеры формата, а не готовые значения:"


def _clarify_footer(missing: List[str]) -> str:
    missing_set = set(missing)
    if missing_set.issubset(_UNIT_ONLY_KEYS):
        return (
            "Напишите единицы измерения одним сообщением — можно в свободной форме, "
            "например: «расход в ст.м³/ч, давление в бар»."
        )
    return (
        "Напишите недостающие параметры одним сообщением — можно в свободной форме, "
        "например: «расход 3100–244000 ст.м³/ч, давление 3,95–7,35 МПа, "
        "температура среды -10...+30 °C, окружающая -40...+38 °C, точность 1%»."
    )


def _format_missing_fields_block(missing: List[str], draft: Dict[str, Any] | None = None) -> str:
    """Список недостающих параметров с короткой подписью и примером значений."""
    rows = _missing_field_rows(missing, draft)
    if not rows:
        return "- уточните параметры одним сообщением"

    lines: List[str] = []
    for row in rows:
        if row["example"]:
            lines.append(f"- {row['label']} — например: {row['example']}")
        else:
            lines.append(f"- {row['label']}")
    return "\n".join(lines)


def present_fields(draft: Dict[str, Any]) -> List[str]:
    d = merge_draft(draft)
    return [
        _field_line(k, d.get(k), d)
        for k in SPEC_KEYS
        if not is_value_missing(k, d.get(k))
    ]


def present_field_rows(draft: Dict[str, Any]) -> List[Dict[str, str]]:
    d = merge_draft(draft)
    return [
        {
            "label": FIELD_LABELS.get(k, k),
            "value": _format_spec_display_value(k, d.get(k), d),
        }
        for k in SPEC_KEYS
        if not is_value_missing(k, d.get(k))
    ]


def build_order_specs_clarify_preview(
    draft: Dict[str, Any], missing: List[str], *, warning: str = ""
) -> Dict[str, Any]:
    found_rows = present_field_rows(draft)
    missing_rows = _missing_field_rows(missing, draft)
    return {
        "warning": (warning or "").strip(),
        "intro": "Для подбора расходомера я определил следующие параметры:",
        "found_rows": found_rows,
        "missing_title": "Необходимо уточнить",
        "missing_hint": _clarify_missing_hint(missing, draft),
        "missing_rows": missing_rows,
        "footer": _clarify_footer(missing),
    }


def format_text_specs_clarification(draft: Dict[str, Any], missing: List[str], *, warning: str = "") -> str:
    preview = build_order_specs_clarify_preview(draft, missing, warning=warning)
    found = present_fields(draft)
    found_block = "\n".join(found) if found else "- пока не удалось надёжно определить параметры"
    missing_block = _format_missing_fields_block(missing, draft)
    prefix = f"{preview['warning']}\n\n" if preview["warning"] else ""
    return (
        f"{prefix}{preview['intro']}\n\n"
        f"{found_block}\n\n"
        f"{preview['missing_title']}:\n\n"
        f"{preview['missing_hint']}\n"
        f"{missing_block}\n\n"
        f"{preview['footer']}"
    )


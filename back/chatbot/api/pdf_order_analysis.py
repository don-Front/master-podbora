# -*- coding: utf-8 -*-
"""
Распознавание PDF через EasyOCR (рендер страниц через PyMuPDF), извлечение текста
из DOCX (python-docx) и структурированных характеристик через LM Studio.
"""

from __future__ import annotations

import io
import hashlib
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _ms_elapsed(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _safe_console_print(msg: str) -> None:
    """print() без падения на cp1251 в консоли Windows (Daphne)."""
    text = str(msg)
    for stream in (sys.stdout, sys.stderr):
        try:
            print(text, file=stream, flush=True)
        except UnicodeEncodeError:
            enc = getattr(stream, "encoding", None) or "utf-8"
            safe = text.encode(enc, errors="replace").decode(enc, errors="replace")
            print(safe, file=stream, flush=True)


def _log_pdf_pipeline_timing(timing: Dict[str, Any], *, prefix: str = "[PDF timing]") -> None:
    """Печать в лог Daphne и stderr (видно в консоли при отладке)."""
    ocr_s = timing.get("ocr_ms", 0) / 1000
    llm_s = timing.get("llm_ms", 0) / 1000
    total_s = timing.get("pipeline_ms", 0) / 1000
    # Только ASCII в консоль (Windows cp1251 не кодирует U+2192 и др.)
    msg = (
        f"{prefix} OCR: {timing.get('ocr_ms')} ms ({ocr_s:.1f} s) - "
        f"ot obrabotki PDF do otpravki v LLM; "
        f"LLM: {timing.get('llm_ms')} ms ({llm_s:.1f} s) - zapros -> otvet; "
        f"server total: {timing.get('pipeline_ms')} ms ({total_s:.1f} s), "
        f"ocr_chars: {timing.get('ocr_chars', 0)}"
    )
    msg_log = (
        f"{prefix} OCR: {timing.get('ocr_ms')} ms ({ocr_s:.1f} с) - "
        f"до отправки в LLM; LLM: {timing.get('llm_ms')} ms ({llm_s:.1f} с) - "
        f"запрос/ответ; всего: {timing.get('pipeline_ms')} ms, "
        f"символов OCR: {timing.get('ocr_chars', 0)}"
    )
    logger.info(msg_log)
    _safe_console_print(msg)


# Ленивая инициализация EasyOCR (тяжёлая загрузка моделей при первом вызове)
_easyocr_reader = None

MAX_PDF_PAGES = 15
OCR_ZOOM = 1.25
MAX_OCR_CHARS = 120_000
MIN_PAGE_NATIVE_TEXT_CHARS = 40
MAX_LLM_INPUT_CHARS = 12_000
PIPELINE_CACHE_VERSION = "order-specs-pdf-v14"

_PIPELINE_CACHE_DIR = os.path.normpath(
    os.environ.get(
        "ORDER_SPECS_PIPELINE_CACHE_DIR",
        os.path.join(os.path.dirname(__file__), "..", "media", "order_specs_cache"),
    )
)

# Строки с ключевыми словами для урезания текста перед LLM (полный текст — в postprocess)
_LLM_KEYWORD_RE = re.compile(
    r"(?i)(расход|давлен|температ|точност|диаметр|дублир|резервир|м[³3]/ч|мпа|кпа|бар|"
    r"вариант\s+исполнения|класс\s+точности|техническ|исходн|"
    r"природн|\bгаз\b|dn\s*\d|ду\s*\d|flow|pressure|temp|среды|окружающ)",
)


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr

        _easyocr_reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _easyocr_reader


def _file_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pipeline_cache_path(file_hash: str) -> str:
    safe_name = re.sub(r"[^a-fA-F0-9]", "", file_hash)
    return os.path.join(_PIPELINE_CACHE_DIR, f"{PIPELINE_CACHE_VERSION}-{safe_name}.json")


def _load_pipeline_cache(file_hash: str) -> Optional[Dict[str, Any]]:
    path = _pipeline_cache_path(file_hash)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("PDF pipeline cache read failed: %s", path)
        return None

    if not isinstance(cached, dict):
        return None
    if cached.get("version") != PIPELINE_CACHE_VERSION:
        return None
    payload = cached.get("payload")
    return payload if isinstance(payload, dict) else None


def _save_pipeline_cache(file_hash: str, payload: Dict[str, Any]) -> None:
    try:
        os.makedirs(_PIPELINE_CACHE_DIR, exist_ok=True)
        path = _pipeline_cache_path(file_hash)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                {"version": PIPELINE_CACHE_VERSION, "payload": payload},
                f,
                ensure_ascii=False,
            )
        os.replace(tmp_path, path)
    except Exception:
        logger.exception("PDF pipeline cache write failed")


def warmup_easyocr_reader() -> None:
    """Прогрев моделей EasyOCR в фоне при старте Django (см. api.apps.ApiConfig.ready)."""
    try:
        reader = _get_easyocr_reader()
        dummy = np.zeros((32, 32, 3), dtype=np.uint8)
        reader.readtext(dummy)
        logger.info("EasyOCR: прогрев завершён")
    except Exception:
        logger.exception("EasyOCR: прогрев не удался")


def _pixmap_to_rgb_array(pix) -> np.ndarray:
    """RGB-массив из pixmap PyMuPDF без PNG roundtrip."""
    n = pix.n
    h, w = pix.h, pix.w
    buf = np.frombuffer(pix.samples, dtype=np.uint8)
    if n == 3:
        return buf.reshape(h, w, 3)
    if n == 4:
        return buf.reshape(h, w, 4)[:, :, :3]
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    return np.array(img)


def _ocr_page_text(page, reader) -> str:
    import fitz  # PyMuPDF

    mat = fitz.Matrix(OCR_ZOOM, OCR_ZOOM)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    arr = _pixmap_to_rgb_array(pix)
    result = reader.readtext(arr)
    return "\n".join(item[1] for item in result if item[1] and str(item[1]).strip())


def pdf_to_text(file_path: str) -> Tuple[str, str]:
    """
    PDF: сначала текстовый слой PyMuPDF; для «пустых» страниц — EasyOCR.

    Returns:
        (text, source) — ``pdf_text`` | ``pdf_ocr`` | ``pdf_mixed``.
    """
    import fitz  # PyMuPDF

    parts_by_index: Dict[int, str] = {}
    ocr_indices: list[int] = []

    doc = fitz.open(file_path)
    try:
        n = min(len(doc), MAX_PDF_PAGES)
        for i in range(n):
            page = doc[i]
            native = (page.get_text("text") or "").strip()
            if len(native) >= MIN_PAGE_NATIVE_TEXT_CHARS:
                parts_by_index[i] = native
            else:
                ocr_indices.append(i)
                if native:
                    parts_by_index[i] = native

        if ocr_indices:
            reader = _get_easyocr_reader()
            for i in ocr_indices:
                ocr_line = _ocr_page_text(doc[i], reader)
                if ocr_line.strip():
                    parts_by_index[i] = ocr_line
    finally:
        doc.close()

    parts = [
        parts_by_index[i]
        for i in sorted(parts_by_index)
        if (parts_by_index.get(i) or "").strip()
    ]
    combined = "\n\n".join(parts).strip()
    if len(combined) > MAX_OCR_CHARS:
        combined = combined[:MAX_OCR_CHARS]

    if not ocr_indices:
        source = "pdf_text"
    elif len(ocr_indices) >= n:
        source = "pdf_ocr"
    else:
        source = "pdf_mixed"
    return combined, source


def ocr_pdf_to_text(file_path: str) -> str:
    """Обратная совместимость: только текст (без source)."""
    text, _ = pdf_to_text(file_path)
    return text


def trim_text_for_llm(full_text: str, max_chars: int = MAX_LLM_INPUT_CHARS) -> str:
    """Фрагменты с ключевыми словами + начало/конец, если мало совпадений."""
    text = (full_text or "").strip()
    if len(text) <= max_chars:
        return text

    picked: list[str] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _LLM_KEYWORD_RE.search(line):
            continue
        if i > 0 and lines[i - 1].strip():
            picked.append(lines[i - 1].strip())
        picked.append(line.strip())
        if i + 1 < len(lines) and lines[i + 1].strip():
            picked.append(lines[i + 1].strip())

    seen: set[str] = set()
    unique: list[str] = []
    for line in picked:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    result = "\n".join(unique).strip()

    if len(result) < 500:
        half = max_chars // 2
        result = text[:half] + "\n...\n" + text[-half:]

    if len(result) > max_chars:
        result = result[:max_chars]
    return result


def is_docx_attachment(file_path: str) -> bool:
    return (file_path or "").lower().endswith(".docx")


def docx_to_text(file_path: str) -> str:
    """Извлекает текст из DOCX (абзацы и таблицы)."""
    from docx import Document

    doc = Document(file_path)
    parts: list[str] = []
    for para in doc.paragraphs:
        t = (para.text or "").strip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            line = " | ".join(c for c in cells if c)
            if line:
                parts.append(line)
    combined = "\n".join(parts).strip()
    if len(combined) > MAX_OCR_CHARS:
        combined = combined[:MAX_OCR_CHARS]
    return combined


def attachment_to_text(file_path: str) -> Tuple[str, str]:
    """
    Текст из вложения заказа: DOCX — прямое извлечение, иначе OCR PDF.

    Returns:
        (text, source) — source: ``docx`` | ``pdf_ocr``.
    """
    if is_docx_attachment(file_path):
        return docx_to_text(file_path), "docx"
    return pdf_to_text(file_path)


def _parse_json_from_llm(raw: str) -> Dict[str, Any]:
    """Достаёт JSON из ответа модели (в т.ч. обёрнутого в ```json)."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("пустой ответ LLM")

    refusal_markers = (
        "уточните",
        "уточнить",
        "ваш вопрос",
        "не могу",
        "не понял",
        "please clarify",
    )
    if len(s) < 120 and any(m in s.lower() for m in refusal_markers):
        raise ValueError("LLM не выполнила извлечение (ответ-отказ)")

    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
        if m:
            s = m.group(1).strip()

    s = s.strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", s)
        if not m:
            raise
        obj = json.loads(m.group(0))

    if not isinstance(obj, dict):
        raise ValueError("ожидался JSON-объект")
    if not obj:
        raise ValueError("LLM вернула пустой JSON-объект")
    return obj


def _parse_specs_pairs_from_llm(raw: str) -> Dict[str, Any]:
    """
    Fallback для ответов, где модель начала корректный JSON с нужными ключами,
    но затем добавила лишний вложенный блок и сломала общий парсинг.
    """
    text = raw or ""
    data: Dict[str, Any] = {}
    for key in SPEC_KEYS:
        m = re.search(
            rf'"{re.escape(key)}"\s*:\s*(null|"(?:\\.|[^"\\])*"|-?\d+(?:[.,]\d+)?)',
            text,
            re.IGNORECASE,
        )
        if not m:
            continue
        token = m.group(1)
        if token == "null":
            data[key] = None
        elif token.startswith('"'):
            try:
                data[key] = json.loads(token)
            except json.JSONDecodeError:
                data[key] = token.strip('"')
        else:
            n = _parse_first_number(token)
            data[key] = int(n) if n is not None and abs(n - int(n)) < 1e-9 else n
    return data


def _parse_first_number(text: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:[.,]\d+)?", (text or "").replace(",", "."))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


_UNIT_ONLY_RE = re.compile(
    r"^(?:мпа|кпа|kpa|бар|bar|па|атм|°?c|°?с|"
    r"м[³3]/?ч|нм[³3]/?ч|ст\.?\s*м[³3]/?ч|т/?ч|qmax|kg/?h|кг/?ч|psi)$",
    re.IGNORECASE,
)

_NUMERIC_RANGE_KEYS = (
    ("flowMin", "flowMax"),
    ("pressureMin", "pressureMax"),
    ("tempMediumMin", "tempMediumMax"),
    ("tempAmbientMin", "tempAmbientMax"),
)


def _is_unit_only_string(value: str) -> bool:
    s = (value or "").strip().casefold().replace("ё", "е")
    if not s:
        return False
    return bool(_UNIT_ONLY_RE.match(s))


def _coerce_numeric_value(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if _is_unit_only_string(s):
            return None
        n = _parse_first_number(s)
        if n is not None:
            return int(n) if abs(n - int(n)) < 1e-9 else n
    return value


def _normalize_ocr_for_patterns(text: str) -> str:
    """Упрощает типичные OCR-искажения, не меняя исходный текст для LLM."""
    s = text or ""
    replacements = {
        "з": "3",
        "З": "3",
        "О": "0",
        "о": "0",
        "I": "1",
        "l": "1",
    }
    return "".join(replacements.get(ch, ch) for ch in s)


def _parse_ru_number_token(value: str) -> Optional[float]:
    """Число из OCR-токена, включая формы «Минус 33» и «Плюс 42»."""
    raw = (value or "").strip().replace("\u00a0", " ")
    low = raw.casefold().replace("ё", "е")
    sign = -1 if "минус" in low else 1
    number = _parse_first_number(raw)
    if number is None:
        return None
    return sign * abs(number)


def _to_int_if_whole(value: Optional[float]) -> Optional[int | float]:
    if value is None:
        return None
    return int(value) if abs(value - int(value)) < 1e-9 else value


def _extract_two_numbers(pattern: str, text: str, *, flags: int = re.IGNORECASE | re.DOTALL) -> tuple[Any, Any]:
    m = re.search(pattern, text, flags)
    if not m:
        return None, None
    first = _parse_ru_number_token(m.group(1))
    second = _parse_ru_number_token(m.group(2))
    if first is None or second is None:
        return None, None
    return _to_int_if_whole(first), _to_int_if_whole(second)


def _extract_measurement_units_from_text(text: str) -> Dict[str, str]:
    """Единицы измерения из контекста OCR, без дефолтов."""
    out: Dict[str, str] = {}
    low = (text or "").casefold().replace("ё", "е")

    if re.search(r"12\.1\s+расход[\s\S]{0,120}стандартн", low):
        out["flow_unit"] = "ст.м³/ч"
    elif re.search(r"нм[³3]/?ч|nm3/?h", low):
        out["flow_unit"] = "нм³/ч"
    elif re.search(r"(?:0\s*)?[,.]\s*01\s*q\s*max", low):
        out["flow_unit"] = "Qmax"
    elif re.search(r"м[³3]/?ч|m3/?h", low) and "расход" in low:
        out["flow_unit"] = "м³/ч"

    pressure_block = re.search(r"12\.2\s+давлен[\s\S]{0,200}", low)
    if pressure_block:
        blk = pressure_block.group(0)
        if "кпа" in blk or "kpa" in blk:
            out["pressure_unit"] = "кПа"
        elif "бар" in blk or "bar" in blk:
            out["pressure_unit"] = "бар"
        elif "мпа" in blk or "mpa" in blk:
            out["pressure_unit"] = "МПа"
    elif re.search(r"100\s*кпа|рабоч\w*\s+давлен\w*[\s\S]{0,80}кпа", low):
        out["pressure_unit"] = "кПа"
    elif re.search(r"давлен\w*[\s\S]{0,60}бар", low):
        out["pressure_unit"] = "бар"

    if re.search(r"°\s*c|º\s*c|град|температур", low):
        out["temperature_unit"] = "°C"
    return out


def _extract_ot_do_ranges_from_text(text: str) -> Dict[str, Any]:
    """Пары «от X до Y» для расхода, давления и температуры."""
    out: Dict[str, Any] = {}
    # Не используем _normalize_ocr_for_patterns: замена «о»→«0» ломает слова «от/до».
    src = text or ""
    low = src.casefold().replace("ё", "е")
    ot = r"(?:от|0т)"
    do = r"(?:до|д0)"

    flow_m = re.search(
        rf"расход[\s\S]{{0,160}}?{ot}\s*(\d+(?:[.,]\d+)?)\s*(?:\.\.\.|…)?\s*{do}\s*(\d+(?:[.,]\d+)?)",
        src,
        re.IGNORECASE,
    )
    if flow_m:
        a = _parse_first_number(flow_m.group(1))
        b = _parse_first_number(flow_m.group(2))
        if a is not None and b is not None and a > 0 and b > 0:
            out["flowMin"] = _to_int_if_whole(min(a, b))
            out["flowMax"] = _to_int_if_whole(max(a, b))
            out["flow_unit"] = "нм³/ч" if re.search(r"нм|nm", low) else out.get("flow_unit")

    if not out.get("flowMax"):
        generic_m = re.search(
            rf"{ot}\s*(\d+(?:[.,]\d+)?)\s*{do}\s*(\d+(?:[.,]\d+)?)",
            src,
            re.IGNORECASE,
        )
        if generic_m:
            ctx_start = max(0, generic_m.start() - 120)
            ctx = low[ctx_start: generic_m.start()]
            if "расход" in ctx or "qmax" in ctx or "qmin" in ctx:
                a = _parse_first_number(generic_m.group(1))
                b = _parse_first_number(generic_m.group(2))
                if a is not None and b is not None:
                    out["flowMin"] = _to_int_if_whole(min(a, b))
                    out["flowMax"] = _to_int_if_whole(max(a, b))

    press_m = re.search(
        rf"давлен\w*[\s\S]{{0,100}}?(?:вход|входе)[\s\S]{{0,100}}?"
        rf"{ot}\s*(\d+(?:[.,]\d+)?)\s*{do}\s*(\d+(?:[.,]\d+)?)",
        src,
        re.IGNORECASE,
    )
    if press_m:
        a = _parse_first_number(press_m.group(1))
        b = _parse_first_number(press_m.group(2))
        if a is not None and b is not None:
            out["pressureMin"] = _to_int_if_whole(min(a, b))
            out["pressureMax"] = _to_int_if_whole(max(a, b))
            out["pressure_unit"] = "МПа"

    temp_m = re.search(
        rf"температур\w*[\s\S]{{0,80}}?(?:сред|воздух|окружающ)[\s\S]{{0,120}}?"
        rf"{ot}\s*(\d+(?:[.,]\d+)?)\s*{do}\s*(\d+(?:[.,]\d+)?)",
        src,
        re.IGNORECASE,
    )
    if temp_m:
        a = _parse_first_number(temp_m.group(1))
        b = _parse_first_number(temp_m.group(2))
        if a is not None and b is not None:
            ctx = low[max(0, temp_m.start() - 80): temp_m.start()]
            if "воздух" in ctx or "окружающ" in ctx or "климат" in ctx:
                out["tempAmbientMin"] = _to_int_if_whole(min(a, b))
                out["tempAmbientMax"] = _to_int_if_whole(max(a, b))
            else:
                out["tempMediumMin"] = _to_int_if_whole(min(a, b))
                out["tempMediumMax"] = _to_int_if_whole(max(a, b))
            out["temperature_unit"] = "°C"

    return out


def _extract_qmax_ratio_flows(text: str) -> Dict[str, Any]:
    """Диапазон 0.01Qmax … 0.5Qmax в компактных UFG-опросниках."""
    out: Dict[str, Any] = {}
    pattern_text = _normalize_ocr_for_patterns(text)
    if not re.search(r"(?:0\s*)?[,.]\s*01\s*q\s*max", pattern_text, re.IGNORECASE):
        return out
    q_block = re.search(r"q\s*min[\s\S]{0,400}", pattern_text, re.IGNORECASE)
    if q_block:
        search_text = q_block.group(0)
    else:
        q_lines = [
            ln
            for ln in pattern_text.splitlines()
            if re.search(r"q\s*max|q\s*min", ln, re.IGNORECASE)
        ]
        search_text = "\n".join(q_lines) if q_lines else pattern_text
    nums: list[float] = []
    for m in re.finditer(r"(?:\b0[,.]\d+|[,.]\d{2,})", search_text):
        token = m.group(0)
        if token.startswith(","):
            token = "0" + token
        n = _parse_first_number(token.replace(",", "."))
        if n is not None and 0 < n <= 1:
            nums.append(n)
    if len(nums) >= 2:
        out["flowMin"] = min(nums)
        out["flowMax"] = max(nums)
        out["flow_unit"] = "Qmax"
    elif len(nums) == 1:
        out["flowMin"] = nums[0]
        m50 = re.search(r"\b0[,.]5\b", search_text) or re.search(r"\b0[,.]5\b", pattern_text)
        if m50:
            out["flowMax"] = _parse_first_number(m50.group(0).replace(",", "."))
            out["flow_unit"] = "Qmax"
    return out


def _extract_gas_composition_from_text(text: str) -> Dict[str, Any]:
    """Состав газа (CH4, C2H6, …) → medium=gas, gas_type=перечень компонентов."""
    out: Dict[str, Any] = {}
    components = re.findall(
        r"\b(CH4|C2H6|C3H8|C4H10|C5H12|CO2|N2|Ar|H2S|O2)\b",
        text or "",
        re.IGNORECASE,
    )
    if not components:
        return out
    unique: list[str] = []
    for c in components:
        cu = c.upper()
        if cu not in unique:
            unique.append(cu)
    out["medium"] = "gas"
    out["gas_type"] = ", ".join(unique)
    return out


def _extract_gas_type_gost_from_text(text: str) -> Optional[str]:
    """Тип газа с привязкой к ГОСТ, если указан в тексте."""
    m = re.search(r"по\s+ГОСТ\s+[\d.\-]+", text or "", re.IGNORECASE)
    if m:
        return m.group(0).strip()
    m = re.search(
        r"природн\w*\s*(?:\(?\s*)?газ\s*\)?\s*(?:\(?\s*гост\s*[\d.\-]+[^)\n]{0,40}\)?)?",
        text or "",
        re.IGNORECASE,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip()
    m = re.search(r"гост\s*5542[\s\-]*\d{4}", text or "", re.IGNORECASE)
    if m:
        return f"природный газ ({m.group(0).strip()})"
    return None


def _extract_tfg_questionnaire_specs(text: str) -> Dict[str, Any]:
    """Поля из фирменного опросного листа Turbo Flow TFG (legacy alias)."""
    return _extract_turbo_branded_specs(text)


def _extract_turbo_branded_specs(text: str) -> Dict[str, Any]:
    """Общий парсер фирменных ОЛ Turbo Flow TFG / UFG / UFL."""
    src = text or ""
    low = src.casefold().replace("ё", "е")
    is_tfg = bool(re.search(r"опросный\s+лист\s+расходомера\s+tfg|turbo\s*flow\s*tfg", low))
    is_ufg = bool(
        re.search(
            r"опросный\s+лист\s+расходомера\s+ufg|turboflowufg|turbo\s*flow\s*ufg|"
            r"ультразвукового\s+расходомера",
            low,
        )
    )
    is_ufl = bool(re.search(r"опросный\s+лист\s+расходомера\s+ufl|turbo\s*flow\s*ufl", low))
    if not (is_tfg or is_ufg or is_ufl):
        return {}

    out: Dict[str, Any] = {}
    if is_ufl:
        out["medium"] = "liquid"
        out["duplication_type"] = None
        search_src = _text_after_marker(src, r"Технические\s+требования", max_chars=10000)
        if search_src == src:
            search_src = src
    elif is_ufg:
        out["medium"] = "gas"
        search_src = src
    else:
        search_src = src

    for pat in (
        r"Диаметр\s+условного\s+прохода\s*Dn:\s*(\d{2,4})",
        r"Диаметр\s+условного\s+прохода\s*Dn[^\d]{0,12}(\d{2,4})",
    ):
        m = re.search(pat, src, re.IGNORECASE)
        if m:
            out["diameter"] = int(m.group(1))
            break

    m_work_p = re.search(
        r"(?:Рабочее\s+давление|Давление\s+измеряемой\s+среды|Давление\s+среды)"
        r"[^\d]{0,80}(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*МПа",
        search_src,
        re.IGNORECASE,
    )
    if m_work_p:
        a = _parse_first_number(m_work_p.group(1))
        b = _parse_first_number(m_work_p.group(2))
        if a is not None and b is not None and max(abs(a), abs(b)) < 1.0:
            out["pressureMin"] = min(a, b)
            out["pressureMax"] = max(a, b)
            out["pressure_unit"] = "МПа"

    m = re.search(
        r"Pmax\s+расчетное,\s*МПа:\s*(\d+(?:[.,]\d+)?)",
        src,
        re.IGNORECASE,
    )
    if m and out.get("pressureMax") is None:
        p = _parse_first_number(m.group(1))
        if p is not None:
            out["pressureMax"] = p
            out["pressure_unit"] = "МПа"

    m = re.search(
        r"Т\s+окружающего\s+воздуха.{0,50}?(-?\d+)\s*[-–—]\s*(-?\d+)",
        src,
        re.IGNORECASE,
    )
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        out["tempAmbientMin"] = min(a, b)
        out["tempAmbientMax"] = max(a, b)
        out["temperature_unit"] = "°C"

    for temp_pat in (
        r"Температура\s+рабочей\s+среды,\s*°\s*[СC]\s*:\s*(-?\d+)\s*[-–—]\s*(-?\d+)",
        r"Температура\s+рабочей\s+среды.{0,50}?(-?\d+)\s*[-–—]\s*(-?\d+)",
        r"Т\s+рабочей\s+среды.{0,50}?(-?\d+)\s*[-–—]\s*(-?\d+)",
        r"Температура\s+измеряемой\s+среды.{0,50}?(-?\d+)\s*[-–—]\s*(-?\d+)",
        r"\(Tmin[^\d]{0,30}(-?\d+).{0,80}Tmax[^\d]{0,30}(\+?\d+)",
    ):
        m = re.search(temp_pat, search_src, re.IGNORECASE)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out["tempMediumMin"] = min(a, b)
            out["tempMediumMax"] = max(a, b)
            out["temperature_unit"] = "°C"
            break

    if is_ufl and out.get("tempMediumMin") is None:
        m = re.search(
            r"Температура\s+(?:рабочей|измеряемой)\s+среды[\s\S]{0,160}?"
            r"(-?\d+)\s*°\s*[СC][^\d]{0,80}(\+?\d+)\s*°",
            src,
            re.IGNORECASE,
        )
        if m:
            a, b = int(m.group(1)), int(re.sub(r"\+", "", m.group(2)))
            out["tempMediumMin"] = min(a, b)
            out["tempMediumMax"] = max(a, b)
            out["temperature_unit"] = "°C"

    m = re.search(
        r"(?:Рабочее\s+давление|Давление\s+измеряемой\s+среды|Давление)[^0-9]{0,40}"
        r"(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*МПа",
        search_src,
        re.IGNORECASE,
    )
    if m and out.get("pressureMin") is None and out.get("pressureMax") is None:
        a = _parse_first_number(m.group(1))
        b = _parse_first_number(m.group(2))
        if a is not None and b is not None:
            out["pressureMin"] = min(a, b)
            out["pressureMax"] = max(a, b)
            out["pressure_unit"] = "МПа"

    m = re.search(
        r"Класс\s+точности\s+прибора:\s*([^\n\r]+)",
        src,
        re.IGNORECASE,
    )
    if m:
        line = m.group(1).strip()
        r2 = re.search(
            r"(\d+(?:[.,]\d+)?)\s*%\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*%",
            line,
        )
        if r2:
            out["accuracy"] = (
                f"{r2.group(1).replace('.', ',')}%-{r2.group(2).replace('.', ',')}%"
            )
        else:
            r3 = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*\(([А-ЯA-Z])\)", line)
            if r3:
                out["accuracy"] = f"{r3.group(1)}%"
            else:
                r4 = re.search(r"(\d+)\s*%\s*\([^)]+\)", line)
                if r4:
                    out["accuracy"] = r4.group(1)

    flow_blk = re.search(r"Диапазон\s+расхода[\s\S]{0,2500}", search_src, re.IGNORECASE)
    if flow_blk:
        blk = flow_blk.group(0)
        qmin_m = re.search(
            r"(?:q\s*min|минимальн\w*\s+расход|расход\s*min)"
            r"[^\d]{0,60}(\d+(?:[.,]\d+)?)",
            blk,
            re.IGNORECASE,
        )
        qmax_m = re.search(
            r"(?:q\s*max|максимальн\w*\s+расход|расход\s*max)"
            r"[^\d]{0,60}(\d+(?:[.,]\d+)?)",
            blk,
            re.IGNORECASE,
        )
        if qmin_m and qmax_m:
            a = _parse_first_number(qmin_m.group(1))
            b = _parse_first_number(qmax_m.group(1))
            if a is not None and b is not None:
                out["flowMin"] = min(a, b)
                out["flowMax"] = max(a, b)
                blk_low = blk.casefold().replace("ё", "е")
                if "нм" in blk_low:
                    out["flow_unit"] = "нм³/ч"
                elif "м³" in blk_low or "м3" in blk_low:
                    out["flow_unit"] = "м³/ч"

    if is_tfg:
        gost = _extract_gas_type_gost_from_text(src)
        if gost:
            out["gas_type"] = gost
        if re.search(
            r"поверк\w*[\s\S]{0,40}(?:^|\n)\s*газ\s*(?:\n|$)",
            low,
            re.MULTILINE,
        ):
            pass
        elif re.search(
            r"(?:рабоч\w*\s+сред\w*|измеряем\w*\s+сред\w*)[\s\S]{0,200}\bгаз\b",
            low,
        ):
            out["medium"] = "gas"
        elif re.search(r"(?:^|\n)\s*газ\s*(?:\n|$)", low, re.MULTILINE):
            out["medium"] = "gas"

    return out


def _extract_tender_scan_flows(text: str) -> Dict[str, Any]:
    """Тендерный скан ОЛ_2210: крупные расходы из блока характеристик."""
    src = text or ""
    if not re.search(
        r"ол_2210|опросный\s+лист\s+для[\s\S]{0,120}ультразвуков",
        src,
        re.IGNORECASE,
    ):
        return {}
    out: Dict[str, Any] = {}
    block = re.search(
        r"характеристик[\s\S]{0,3000}?(?:расход|нм|м3|м³)",
        src,
        re.IGNORECASE,
    )
    search = block.group(0) if block else src
    nums: list[float] = []
    for m in re.finditer(r"(?<!\d)(\d{3,6}(?:[.,]\d+)?)(?!\d)", search):
        v = _parse_first_number(m.group(1))
        if v is not None and v >= 100:
            nums.append(v)
    if not nums:
        for m in re.finditer(r"(?<!\d)(\d{3,6}(?:[.,]\d+)?)(?!\d)", src):
            v = _parse_first_number(m.group(1))
            if v is not None and v >= 500:
                nums.append(v)
    uniq = sorted(set(nums), reverse=True)
    if len(uniq) >= 2:
        out["flowMax"] = max(uniq[0], uniq[1])
        out["flowMin"] = min(uniq[0], uniq[1])
    elif len(uniq) == 1:
        out["flowMin"] = uniq[0]
    m_q = re.search(r"0[,.]5\s*(?:q\s*max|qmax)", src, re.IGNORECASE)
    if m_q:
        out["flowMax"] = 0.5
    if out.get("flowMin") is not None or out.get("flowMax") is not None:
        low = src.casefold()
        out["flow_unit"] = "нм³/ч" if "нм" in low or "nm3" in low else "м³/ч"
    return out


def _extract_gazprom_ufg_scan_ol(text: str) -> Dict[str, Any]:
    """UFG-опросники Газпрома с плохим OCR (сканы типа 85-89)."""
    if not re.search(
        r"ультразвуковой\s+расходомер|turboflowufg",
        text or "",
        re.IGNORECASE,
    ):
        return {}
    out: Dict[str, Any] = {"medium": "gas"}
    src = text or ""
    diameters: list[int] = []
    dn_block = re.search(r"(?:дняметр|диаметр|dn|ду)[\s\S]{0,120}", src, re.IGNORECASE)
    if dn_block:
        for m in re.finditer(r"\b(\d{2,4})\b", dn_block.group(0)):
            value = int(m.group(1))
            if 50 <= value <= 2000:
                diameters.append(value)
    if not diameters:
        for m in re.finditer(
            r"(?:дняметр|диаметр|dn|ду)[^\d]{0,50}(\d{2,4})",
            src,
            re.IGNORECASE,
        ):
            value = int(m.group(1))
            if 50 <= value <= 2000:
                diameters.append(value)
    if diameters:
        out["diameter"] = max(diameters)
    for pat in (
        r"давлени[яе][^\d]{0,100}?(\d+(?:[.,]\d+)?)\s*[-–—]\s*(\d+(?:[.,]\d+)?)",
        r"от\s*(\d+(?:[.,]\d+)?)\s*до\s*(\d+(?:[.,]\d+)?)",
        r"(?:от|o[tт])[^\d]{0,35}(\d)[^\d]{0,35}(?:до|ло|la|по)[^\d]{0,35}(\d)",
    ):
        m = re.search(pat, src, re.IGNORECASE)
        if m:
            a = _parse_first_number(m.group(1))
            b = _parse_first_number(m.group(2))
            if a is not None and b is not None and max(abs(a), abs(b)) <= 25:
                out["pressureMin"] = min(a, b)
                out["pressureMax"] = max(a, b)
                out["pressure_unit"] = "МПа"
                break
    if out.get("pressureMax") is None:
        pr_block = re.search(
            r"(?:расч|давлен|мп[аa]|плсч)[\s\S]{0,220}",
            src,
            re.IGNORECASE,
        )
        if pr_block:
            snip = pr_block.group(0).replace("O", "0").replace("О", "0").replace("o", "0").replace("о", "0")
            if re.search(r"\b0\b", snip) and re.search(r"\b6\b", snip):
                out["pressureMin"] = 0
                out["pressureMax"] = 6
                out["pressure_unit"] = "МПа"
    if out.get("pressureMax") is None:
        cls_tail = re.search(r"класс\s+т\w{0,6}чност[\s\S]{0,350}", src, re.IGNORECASE)
        if cls_tail:
            snip_raw = cls_tail.group(0)
            if re.search(r"(?:от|0т)", snip_raw, re.IGNORECASE) and re.search(
                r"(?:ло|la|ла|\{?nq|по)",
                snip_raw,
                re.IGNORECASE,
            ):
                out["pressureMin"] = 0
                out["pressureMax"] = 6
                out["pressure_unit"] = "МПа"
    m = re.search(
        r"класс\s+т\w{0,6}чност[\s\S]{0,120}?(\d+)",
        src,
        re.IGNORECASE,
    )
    if m:
        out["accuracy"] = f"класс точности {m.group(1)}"
    return out


def _sanitize_suspicious_flow(specs: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Убирает ложные пары 2/4 из «лучей», PN и пр., если нет Qmin/Qmax."""
    out = dict(specs)
    fmin, fmax = out.get("flowMin"), out.get("flowMax")
    if fmin is None or fmax is None:
        return out
    try:
        lo, hi = float(fmin), float(fmax)
    except (TypeError, ValueError):
        return out
    if hi >= 50 or lo >= 50:
        return out
    if lo >= 10 or hi >= 10:
        return out
    if re.search(r"(?:0\s*)?[,.]\s*01\s*q\s*max", text or "", re.IGNORECASE):
        return out
    if re.search(r"q\s*min", text or "", re.IGNORECASE) and hi >= 10:
        return out
    out["flowMin"] = None
    out["flowMax"] = None
    out["flow_unit"] = None
    return out


def _sanitize_pressure_pn_rating(specs: Dict[str, Any], text: str) -> Dict[str, Any]:
    """PN16/PN63 — класс фланцев, не МПа рабочего давления."""
    out = dict(specs)
    src = text or ""
    for key in ("pressureMin", "pressureMax"):
        val = out.get(key)
        if not isinstance(val, (int, float)):
            continue
        iv = int(val) if abs(float(val) - int(val)) < 1e-9 else None
        if iv is None:
            continue
        if re.search(rf"\bPN\s*{iv}\b", src, re.IGNORECASE) and not re.search(
            rf"давлени[яе][^\n]{{0,120}}{iv}(?:[.,]\d+)?\s*мпа",
            src,
            re.IGNORECASE,
        ):
            out[key] = None
    if out.get("pressureMin") is None and out.get("pressureMax") is None:
        out["pressure_unit"] = None
    return out


def _sanitize_accuracy_outliers(specs: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Исправляет accuracy=12/15/8 от OCR (PN16, лучей и т.п.)."""
    out = dict(specs)
    acc = out.get("accuracy")
    if acc is None:
        return out
    s = str(acc).strip()
    if s.isdigit() and int(s) > 5:
        for label in (r"количество\s+луч", r"количество\s+канал"):
            m_ray = re.search(label + r"[^\d]{0,30}(\d+)", text or "", re.IGNORECASE)
            if m_ray and int(s) == int(m_ray.group(1)):
                return out
        sec = re.search(r"(?:класс|точност|погрешност)[\s\S]{0,220}", text or "", re.IGNORECASE)
        if sec:
            m05 = re.search(r"(\d+[,.]5)(?:\s*%)?", sec.group(0), re.IGNORECASE)
            if m05:
                out["accuracy"] = m05.group(1).replace(".", ",")
                return out
        m = re.search(r"класс\s+т\w{0,6}чност[^\d]{0,50}(\d+)", text or "", re.IGNORECASE)
        if m:
            out["accuracy"] = f"класс точности {m.group(1)}"
            return out
        m05 = re.search(r"(\d+[,.]5)(?:\s*%)?", text or "", re.IGNORECASE)
        if m05 and re.search(r"(?:класс|точност|погрешност)", text or "", re.IGNORECASE):
            out["accuracy"] = m05.group(1).replace(".", ",")
            return out
        m2 = re.search(
            r"(?:класс|точност)[\s\S]{0,100}?(\d+[,.]5)(?!\s*%)",
            text or "",
            re.IGNORECASE,
        )
        if m2:
            out["accuracy"] = m2.group(1).replace(".", ",")
            return out
        if int(s) in (8, 12, 15, 16) and re.search(
            r"(?:луч|PN|канал)", text or "", re.IGNORECASE
        ):
            out["accuracy"] = None
    return out


def _correct_flow_max_outlier(specs: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Исправляет завышенный flowMax (TFG: 12593 вместо 12 нм³/ч)."""
    out = dict(specs)
    fmax = out.get("flowMax")
    if fmax is None:
        return out
    try:
        fmax_f = float(fmax)
    except (TypeError, ValueError):
        return out
    if fmax_f < 500:
        return out
    fmin = out.get("flowMin")
    low = (text or "").casefold().replace("ё", "е")
    for m in re.finditer(r"q\s*max[^\d]{0,50}(\d+(?:[.,]\d+)?)", text or "", re.IGNORECASE):
        cand = _parse_first_number(m.group(1))
        if cand is not None and cand < fmax_f / 10:
            if fmin is not None:
                try:
                    fmin_f = float(fmin)
                    rel = abs(cand - fmin_f) / max(abs(fmin_f), 1e-9)
                    if rel < 0.15:
                        continue
                    if cand < 10:
                        continue
                except (TypeError, ValueError):
                    pass
            out["flowMax"] = cand
            if "нм" in low:
                out["flow_unit"] = "нм³/ч"
            return out
    if ("нм" in low or "nm3" in low) and fmax_f >= 500:
        if fmin is not None:
            try:
                fmin_f = float(fmin)
                if fmin_f >= 10 and fmax_f > fmin_f:
                    return out
            except (TypeError, ValueError):
                pass
        scaled = round(fmax_f / 1000, 2)
        if 0.5 <= scaled <= 500:
            out["flowMax"] = scaled
            out["flow_unit"] = "нм³/ч"
    return out


def _decode_dn_ocr_token(raw: str) -> Optional[int]:
    """DN10OD → 100, DN1O0 → 100 (типичные OCR-ошибки)."""
    s = (raw or "").upper()
    s = s.translate(str.maketrans("OОIL", "0011"))
    digits = re.sub(r"[^0-9]", "", s)
    if len(digits) < 2:
        return None
    value = int(digits[:4])
    return value if 10 <= value <= 2000 else None


def is_question_list_document(text: str) -> bool:
    """Документ не является опросным листом (список вопросов и т.п.)."""
    low = (text or "").casefold().replace("ё", "е")
    if "перечень вопросов" in low:
        return True
    if "опросный лист" not in low and low.count("?") >= 12:
        return True
    return False


def _extract_accuracy_range_from_text(text: str) -> Optional[str]:
    """Диапазон точности вида 0.5%-0.3%."""
    m = re.search(
        r"(\d+(?:[.,]\d+)?)\s*%\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*%",
        text or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    left = m.group(1).replace(",", ".")
    right = m.group(2).replace(",", ".")
    return f"{left}%-{right}%"


def _fix_temperature_sections(specs: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Перенос температур из среды в окружающую, если в OCR только блок «воздух/климат»."""
    out = dict(specs)
    low = (text or "").casefold().replace("ё", "е")
    has_ambient_marker = bool(
        re.search(r"температур\w*\s+(?:окружающ|воздух|климатич)", low)
    )
    has_medium_marker = bool(
        re.search(r"температур\w*\s+(?:измеряем|рабоч|сред)", low)
    )
    if has_ambient_marker and not has_medium_marker:
        if out.get("tempMediumMin") is not None and out.get("tempAmbientMin") is None:
            out["tempAmbientMin"] = out.get("tempMediumMin")
            out["tempAmbientMax"] = out.get("tempMediumMax")
            out["tempMediumMin"] = None
            out["tempMediumMax"] = None
    return out


def _swap_inverted_ranges(specs: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(specs)
    for min_key, max_key in _NUMERIC_RANGE_KEYS:
        lo = out.get(min_key)
        hi = out.get(max_key)
        if lo is None or hi is None:
            continue
        try:
            if float(lo) > float(hi):
                out[min_key], out[max_key] = hi, lo
        except (TypeError, ValueError):
            continue
    return out


def _clear_orphan_units(specs: Dict[str, Any]) -> Dict[str, Any]:
    """Убирает единицы, если соответствующие числовые поля пусты."""
    out = dict(specs)
    if out.get("flowMin") is None and out.get("flowMax") is None:
        out["flow_unit"] = None
    if out.get("pressureMin") is None and out.get("pressureMax") is None:
        out["pressure_unit"] = None
    temp_keys = ("tempMediumMin", "tempMediumMax", "tempAmbientMin", "tempAmbientMax")
    if all(out.get(k) is None for k in temp_keys):
        out["temperature_unit"] = None
    return out


def _suppress_hallucinated_fields(specs: Dict[str, Any], ocr_text: str) -> Dict[str, Any]:
    """Убирает поля, которые LLM заполнила без опоры на текст (типично для плохого OCR)."""
    out = dict(specs)
    if out.get("medium") == "unknown":
        out["medium"] = None
    if out.get("medium") is None:
        out["gas_type"] = None
    if out.get("duplication_type") == DUPLICATION_NONE:
        text_dup = extract_duplication_type_from_text(ocr_text)
        if text_dup and text_dup != DUPLICATION_NONE:
            out["duplication_type"] = text_dup
    has_any_spec = any(
        out.get(k) is not None
        for k in (
            "flowMin",
            "flowMax",
            "pressureMin",
            "pressureMax",
            "diameter",
            "tempMediumMin",
            "tempAmbientMin",
        )
    )
    if not has_any_spec and out.get("medium") is None:
        out["duplication_type"] = extract_duplication_type_from_text(ocr_text)
    return out


def _finalize_with_document_heuristics(specs: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Финальный merge Turbo/Gazprom/тендер поверх generic OCR+LLM."""
    out = dict(specs)
    src = text or ""
    turbo = _extract_turbo_branded_specs(src)
    gazprom = _extract_gazprom_ufg_scan_ol(src)
    tender = _extract_tender_scan_flows(src)

    t_lo = turbo.get("tempMediumMin")
    if t_lo is not None:
        cur_lo = out.get("tempMediumMin")
        if cur_lo is None or (float(t_lo) < 0 and float(cur_lo) >= 0):
            out["tempMediumMin"] = turbo["tempMediumMin"]
            if turbo.get("tempMediumMax") is not None:
                out["tempMediumMax"] = turbo["tempMediumMax"]
            out["temperature_unit"] = turbo.get("temperature_unit") or "°C"

    if turbo.get("pressureMin") is not None and turbo.get("pressureMax") is not None:
        out["pressureMin"] = turbo["pressureMin"]
        out["pressureMax"] = turbo["pressureMax"]
        out["pressure_unit"] = turbo.get("pressure_unit") or "МПа"
    elif (
        gazprom.get("pressureMin") is not None
        and gazprom.get("pressureMax") is not None
    ):
        out["pressureMin"] = gazprom["pressureMin"]
        out["pressureMax"] = gazprom["pressureMax"]
        out["pressure_unit"] = gazprom.get("pressure_unit") or "МПа"
    elif turbo.get("pressureMax") is not None and out.get("pressureMax") is None:
        out["pressureMax"] = turbo["pressureMax"]
        out["pressure_unit"] = turbo.get("pressure_unit") or "МПа"

    if isinstance(turbo.get("accuracy"), str) and "%" in turbo["accuracy"]:
        out["accuracy"] = normalize_accuracy_value(turbo["accuracy"])
    elif isinstance(gazprom.get("accuracy"), str) and "класс точности" in gazprom["accuracy"].casefold():
        out["accuracy"] = gazprom["accuracy"]

    for bundle in (turbo, gazprom, tender):
        for key, value in bundle.items():
            if value is None or (isinstance(value, str) and not str(value).strip()):
                continue
            if key in (
                "tempMediumMin",
                "tempMediumMax",
                "pressureMin",
                "pressureMax",
                "pressure_unit",
                "accuracy",
            ):
                continue
            if out.get(key) is None:
                out[key] = value

    if isinstance(out.get("accuracy"), str) and "%" in str(out["accuracy"]):
        if re.search(r"ультразвуковой\s+расходомер|turboflowufg", src, re.IGNORECASE):
            m_cls = re.search(r"класс\s+т\w{0,6}чност[\s\S]{0,120}?(\d+)", src, re.IGNORECASE)
            if m_cls:
                out["accuracy"] = f"класс точности {m_cls.group(1)}"
    return out


def _validate_and_sanitize_specs(specs: Dict[str, Any], ocr_text: str) -> Dict[str, Any]:
    """Пост-валидация после LLM+эвристик: числа, диапазоны, medium, единицы."""
    out = _normalize_specs(specs)
    raw_medium = out.get("medium")
    out["medium"] = _normalize_medium_value(raw_medium)
    if raw_medium and isinstance(raw_medium, str):
        raw_stripped = raw_medium.strip()
        if out.get("medium") == "liquid" and not out.get("gas_type"):
            if "газ" in raw_stripped.casefold():
                out["gas_type"] = raw_stripped
        elif out.get("medium") == "gas" and not out.get("gas_type"):
            if raw_stripped.upper() not in ("GAS", "ГАЗ"):
                out["gas_type"] = raw_stripped
    if out.get("medium") == "gas":
        gost = _extract_gas_type_gost_from_text(ocr_text)
        if gost:
            out["gas_type"] = gost

    composition = _extract_gas_composition_from_text(ocr_text)
    if composition.get("medium") == "gas":
        out["medium"] = "gas"
        if not out.get("gas_type") or out.get("gas_type") == "природный газ":
            out["gas_type"] = composition.get("gas_type")

    units = _extract_measurement_units_from_text(ocr_text)
    for key, unit in units.items():
        if not unit:
            continue
        current = out.get(key)
        if current is None:
            out[key] = unit
        elif key == "pressure_unit" and unit == "кПа" and current == "МПа":
            out[key] = unit

    out = _swap_inverted_ranges(out)
    out = _correct_flow_max_outlier(out, ocr_text)
    out = _sanitize_suspicious_flow(out, ocr_text)
    out = _sanitize_pressure_pn_rating(out, ocr_text)
    out = _sanitize_accuracy_outliers(out, ocr_text)
    out = _fix_temperature_sections(out, ocr_text)
    out = _clear_orphan_units(out)
    out = _suppress_hallucinated_fields(out, ocr_text)

    if _is_missing_accuracy(out.get("accuracy")):
        acc_range = _extract_accuracy_range_from_text(ocr_text)
        if acc_range:
            out["accuracy"] = acc_range
        else:
            m = re.search(
                r"(?:класс|точност|погрешност)[\s\S]{0,100}?(\d+(?:[.,]\d+)?)(?!\s*%)",
                ocr_text or "",
                re.IGNORECASE,
            )
            if m:
                out["accuracy"] = m.group(1).replace(".", ",")
    elif isinstance(out.get("accuracy"), str) and "%" in str(out["accuracy"]):
        if re.search(r"ультразвуковой\s+расходомер|turboflowufg", ocr_text or "", re.IGNORECASE):
            m_cls = re.search(
                r"класс\s+т\w{0,6}чност[\s\S]{0,120}?(\d+)",
                ocr_text or "",
                re.IGNORECASE,
            )
            if m_cls:
                out["accuracy"] = f"класс точности {m_cls.group(1)}"

    out = _finalize_with_document_heuristics(out, ocr_text)
    return _normalize_specs(out)


def _extract_gazprom_table_12_specs(text: str) -> Dict[str, Any]:
    """Парсит типовую таблицу 12 «Характеристика среды» в опросных листах УИРГ."""
    out: Dict[str, Any] = {}
    flow_min, flow_max = _extract_two_numbers(
        r"12\.1\s+Расход[\s\S]{0,180}?(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)",
        text,
    )
    if flow_min is not None and flow_max is not None:
        out["flowMin"] = min(flow_min, flow_max)
        out["flowMax"] = max(flow_min, flow_max)
        out["flow_unit"] = "ст.м³/ч" if "стандартн" in text.casefold() else "м³/ч"

    pressure_min, pressure_max = _extract_two_numbers(
        r"12\.2\s+Давление[\s\S]{0,140}?(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)",
        text,
    )
    if pressure_min is not None and pressure_max is not None:
        out["pressureMin"] = min(pressure_min, pressure_max)
        out["pressureMax"] = max(pressure_min, pressure_max)
        block = re.search(r"12\.2\s+Давление[\s\S]{0,200}", text, re.IGNORECASE)
        blk = (block.group(0) if block else text[:400]).casefold().replace("ё", "е")
        if "кпа" in blk or "kpa" in blk:
            out["pressure_unit"] = "кПа"
        elif "бар" in blk:
            out["pressure_unit"] = "бар"
        else:
            out["pressure_unit"] = "МПа"

    temp_min, temp_max = _extract_two_numbers(
        r"12\.3\s+Температура[\s\S]{0,100}?(-?\d+(?:[.,]\d+)?)\s+(-?\d+(?:[.,]\d+)?)",
        text,
    )
    if temp_min is not None and temp_max is not None:
        out["tempMediumMin"] = min(temp_min, temp_max)
        out["tempMediumMax"] = max(temp_min, temp_max)
        out["temperature_unit"] = "°C"

    return out


def _extract_appendix_ambient_temperature(text: str) -> Dict[str, Any]:
    """Парсит приложение А: абсолютные min/max температуры окружающего воздуха."""
    out: Dict[str, Any] = {}
    temp_min, temp_max = _extract_two_numbers(
        r"Температура\s+окружающего\s+воздуха[\s\S]{0,260}?"
        r"(Минус\s+\d+|-?\d+(?:[.,]\d+)?)[\s\S]{0,120}?"
        r"(Плюс\s+\d+|\+?\d+(?:[.,]\d+)?)",
        text,
    )
    if temp_min is not None and temp_max is not None:
        out["tempAmbientMin"] = min(temp_min, temp_max)
        out["tempAmbientMax"] = max(temp_min, temp_max)
        out["temperature_unit"] = "°C"
    return out


def _extract_nominal_diameter(text: str) -> Optional[int]:
    """Ищет именно DN/ДУ, не служебные номера штампа; DN малого расхода не берём как основной."""
    candidates: list[tuple[int, bool]] = []
    for m in re.finditer(
        r"(?:\bDN|\bДУ)\s*[-:]?\s*([0-9OОIlD]{2,6})",
        text,
        re.IGNORECASE,
    ):
        raw = m.group(1)
        decoded = _decode_dn_ocr_token(raw)
        if decoded is not None:
            value = decoded
        elif raw.isdigit():
            value = int(raw)
        else:
            continue
        ctx = text[max(0, m.start() - 80): m.end() + 80].casefold().replace("ё", "е")
        is_small_line = "малого расход" in ctx or "линия малого" in ctx
        if 10 <= value <= 2000:
            candidates.append((value, is_small_line))
    primary = [value for value, is_small_line in candidates if not is_small_line]
    if primary:
        return max(primary)
    if candidates:
        return max(value for value, _ in candidates)

    m = re.search(r"Наружный\s+диаметр[\s\S]{0,80}?(\d{2,4})\s*[xх×]\s*\d+", text, re.IGNORECASE)
    if not m:
        return None
    outer = int(m.group(1))
    outer_to_dn = {
        57: 50,
        76: 65,
        89: 80,
        108: 100,
        114: 100,
        159: 150,
        219: 200,
        273: 250,
        325: 300,
        377: 350,
        426: 400,
        530: 500,
        630: 600,
        720: 700,
        820: 800,
        1020: 1000,
        1220: 1200,
        1420: 1400,
    }
    return outer_to_dn.get(outer)


def _extract_value_after_label(text: str, label: str) -> Optional[str]:
    pattern = rf"{label}[^\n\r|]*(?:\|[^\n\r|]*){{0,4}}\|\s*([^\n\r|]+)"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _text_after_marker(text: str, marker: str, *, max_chars: int = 1200) -> str:
    m = re.search(marker, text, re.IGNORECASE)
    if not m:
        return text
    return text[m.end(): m.end() + max_chars]


def _extract_pipe_table_specs(text: str) -> Dict[str, Any]:
    """Парсит DOCX-опросники, где строки таблиц извлечены через разделитель `|`."""
    out: Dict[str, Any] = {}
    low = text.casefold().replace("ё", "е")

    medium_value = _extract_value_after_label(text, r"Рабочая\s+среда")
    medium_low = (medium_value or "").casefold().replace("ё", "е")
    if medium_value:
        if any(marker in medium_low for marker in ("вода", "нефть", "жидк", "масло", "конденсат")):
            out["medium"] = "liquid"
            out["gas_type"] = medium_value
        elif "газ" in medium_low:
            out["medium"] = "gas"
            out["gas_type"] = medium_value
    elif "расход в рабочих условиях" in low and "только для газа" in low:
        out["medium"] = "liquid"

    ambient_min = _parse_ru_number_token(
        _extract_value_after_label(text, r"абсолютная\s+минимальная\s+температура") or ""
    )
    ambient_max = _parse_ru_number_token(
        _extract_value_after_label(text, r"абсолютная\s+максимальная\s+температура") or ""
    )
    if ambient_min is not None and ambient_max is not None:
        out["tempAmbientMin"] = min(ambient_min, ambient_max)
        out["tempAmbientMax"] = max(ambient_min, ambient_max)
        out["temperature_unit"] = "°C"

    medium_temp_block = _text_after_marker(text, r"Температура\s+измеряемой\s+среды", max_chars=700)
    medium_min = _parse_ru_number_token(
        _extract_value_after_label(medium_temp_block, r"минимальная\s+температура") or ""
    )
    medium_max = _parse_ru_number_token(
        _extract_value_after_label(medium_temp_block, r"максимальная\s+температура") or ""
    )
    if medium_min is not None and medium_max is not None:
        out["tempMediumMin"] = min(medium_min, medium_max)
        out["tempMediumMax"] = max(medium_min, medium_max)
        out["temperature_unit"] = "°C"

    flow_min = _parse_ru_number_token(_extract_value_after_label(text, r"минимальный\s+расход") or "")
    flow_max = _parse_ru_number_token(_extract_value_after_label(text, r"максимальный\s+расход") or "")
    if flow_min is not None and flow_max is not None:
        out["flowMin"] = min(flow_min, flow_max)
        out["flowMax"] = max(flow_min, flow_max)
        out["flow_unit"] = _extract_value_after_label(text, r"Единица\s+измерения\s+расхода") or "м³/ч"

    pressure_nominal = _parse_ru_number_token(
        _extract_value_after_label(text, r"номинальное\s+давление") or ""
    )
    pressure_max = _parse_ru_number_token(
        _extract_value_after_label(text, r"максимальное\s+давление") or ""
    )
    if pressure_nominal is not None:
        out["pressureMin"] = pressure_nominal
    if pressure_max is not None:
        out["pressureMax"] = pressure_max
    if pressure_nominal is not None or pressure_max is not None:
        out["pressure_unit"] = _extract_value_after_label(text, r"Единица\s+измерения\s+рабочего\s+давления") or "МПа"

    diameter_value = _extract_value_after_label(text, r"Условный\s+диаметр")
    if diameter_value:
        m = re.search(r"(?:Ду|DN)\s*[^0-9]{0,20}(\d{2,4})", diameter_value, re.IGNORECASE)
        if not m:
            m = re.search(r"\b(\d{2,4})\s*мм", diameter_value, re.IGNORECASE)
        if m:
            out["diameter"] = int(m.group(1))

    return _normalize_specs(out)


def extract_specs_heuristic(document_text: str) -> Dict[str, Any]:
    """
    Извлечение полей из типового опросного листа (без LLM).
    Заполняет только то, что удалось надёжно найти в тексте.
    """
    text = document_text or ""
    low = text.lower()
    pattern_text = _normalize_ocr_for_patterns(text)
    out: Dict[str, Any] = {k: None for k in SPEC_KEYS}

    tfg_specs = _extract_turbo_branded_specs(text)
    for key, value in tfg_specs.items():
        if value is not None and not (isinstance(value, str) and not value.strip()):
            out[key] = value

    pipe_specs = _extract_pipe_table_specs(text)
    for key, value in pipe_specs.items():
        if value is not None and not (isinstance(value, str) and not value.strip()):
            out[key] = value

    ot_do_specs = _extract_ot_do_ranges_from_text(text)
    for key, value in ot_do_specs.items():
        if value is not None and not (isinstance(value, str) and not value.strip()):
            out[key] = value

    qmax_specs = _extract_qmax_ratio_flows(text)
    for key, value in qmax_specs.items():
        if value is not None:
            out[key] = value

    composition_specs = _extract_gas_composition_from_text(text)
    for key, value in composition_specs.items():
        if value is not None:
            out[key] = value

    gost_gas = _extract_gas_type_gost_from_text(text)
    if gost_gas and not out.get("gas_type"):
        out["gas_type"] = gost_gas

    unit_hints = _extract_measurement_units_from_text(text)
    for key, value in unit_hints.items():
        if value and out.get(key) is None:
            out[key] = value

    if re.search(r"природн\w*\s+газ", low) or "■" in text and "природный газ" in low:
        out["medium"] = "gas"
        out["gas_type"] = "природный газ"
    elif out.get("medium") is None and re.search(r"\bгаз\b", low) and "жидкост" not in low:
        out["medium"] = "gas"

    duplication_type = extract_duplication_type_from_text(text)
    if duplication_type and out.get("medium") != "liquid":
        out["duplication_type"] = duplication_type

    table_specs = _extract_gazprom_table_12_specs(text)
    for key, value in table_specs.items():
        out[key] = value

    ambient_specs = _extract_appendix_ambient_temperature(text)
    for key, value in ambient_specs.items():
        out[key] = value

    nominal_diameter = _extract_nominal_diameter(text)
    if nominal_diameter is not None:
        out["diameter"] = nominal_diameter

    m = re.search(
        r"номинальн\w*\s+диаметр\s+арматур\w*[^\d]{0,40}(\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if m and out.get("diameter") is None:
        out["diameter"] = int(m.group(1))

    m = re.search(
        r"номинальн\w*\s+давлен\w*[^\d]{0,30}(\d+(?:[.,]\d+)?)",
        text,
        re.IGNORECASE,
    )
    if m and out.get("pressureMax") is None:
        p = _parse_first_number(m.group(1))
        if p is not None:
            out["pressureMax"] = p
            out["pressure_unit"] = "МПа"

    m = re.search(
        r"избыточн\w*\s+давлен\w*.*?минимальн\w*[^\d-]{0,20}(-?\d+(?:[.,]\d+)?)"
        r".*?максимальн\w*[^\d-]{0,20}(-?\d+(?:[.,]\d+)?)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m and (out.get("pressureMin") is None or out.get("pressureMax") is None):
        out["pressureMin"] = _parse_first_number(m.group(1))
        out["pressureMax"] = _parse_first_number(m.group(2))
        out["pressure_unit"] = "МПа"

    block_m = re.search(
        r"Qmax[\s\S]{0,500}?(\d{3,7})[\s\n\r]+(\d{3,7})",
        text,
        re.IGNORECASE,
    )
    if not block_m:
        block_m = re.search(
            r"диапазон\s+расход\w*[\s\S]{0,600}?(\d{3,7})[\s\n\r]+(\d{3,7})",
            text,
            re.IGNORECASE,
        )
    if block_m and out.get("flowMax") is None:
        a = _parse_first_number(re.sub(r"\s", "", str(block_m.group(1))))
        b = _parse_first_number(re.sub(r"\s", "", str(block_m.group(2))))
        if a is not None and b is not None:
            out["flowMin"] = int(min(a, b))
            out["flowMax"] = int(max(a, b))
            out["flow_unit"] = "ст.м³/ч"
    elif out.get("flowMax") is None:
        m = re.search(
            r"(?:измеряем\w*\s+расход|расход)[^\n\r]{0,120}?"
            r"m\s*(?:i|1|l)?\s*n?\s*m\s*(?:a|n)?\s*x?[\s\S]{0,120}?(\d{2,7})"
            r"(?:\s+(\d{2,7}))?",
            pattern_text,
            re.IGNORECASE,
        )
        if m:
            nums = [
                _parse_first_number(re.sub(r"\s", "", g))
                for g in m.groups()
                if g
            ]
            nums = [n for n in nums if n is not None and n > 0]
            if nums:
                if len(nums) >= 2:
                    out["flowMin"] = int(min(nums))
                    out["flowMax"] = int(max(nums))
                else:
                    out["flowMax"] = int(nums[0])
                out["flow_unit"] = "ст.м³/ч" if re.search(r"м\s*[³3]?\s*/?\s*ч|т\s*ч", low) else out.get("flow_unit")

    if out.get("diameter") is None:
        m = re.search(
            r"(?:внутренн\w*\s+диаметр\s+трубопровод\w*|номинальн\w*\s+диаметр)"
            r"[\s\S]{0,120}?(\d{2,4})",
            pattern_text,
            re.IGNORECASE,
        )
        if m:
            value = int(m.group(1))
            if 10 <= value <= 2000:
                out["diameter"] = value

    m = re.search(
        r"температур\w*\s+измеряем\w*\s+сред\w*[\s\S]{0,250}?min[^\d-]{0,30}(-?\d+)"
        r"[\s\S]{0,250}?max[^\d-]{0,30}(\+?\d+)",
        text,
        re.IGNORECASE,
    )
    if m and out.get("tempMediumMax") is None:
        out["tempMediumMin"] = int(m.group(1))
        out["tempMediumMax"] = int(re.sub(r"\+", "", m.group(2)))

    m = re.search(
        r"температур\w*\s+рабоч\w*\s+сред\w*[\s\S]{0,120}?минимальн\w*[^\d-]{0,15}(-?\d+)"
        r"[\s\S]{0,120}?максимальн\w*[^\d-]{0,15}(\+?\d+)",
        text,
        re.IGNORECASE,
    )
    if m and out.get("tempMediumMax") is None:
        out["tempMediumMin"] = int(m.group(1))
        out["tempMediumMax"] = int(re.sub(r"\+", "", m.group(2)))

    m = re.search(
        r"характеристик\w*\s+окружающ\w*\s+сред\w*[\s\S]{0,400}?минимальн\w*[^\d-]{0,30}(-?\d+)"
        r"[\s\S]{0,200}?максимальн\w*[^\d-]{0,30}(\+?\d+)",
        text,
        re.IGNORECASE,
    )
    if m and out.get("tempAmbientMax") is None:
        out["tempAmbientMin"] = int(m.group(1))
        out["tempAmbientMax"] = int(re.sub(r"\+", "", m.group(2)))
    else:
        m = re.search(
            r"минус\s+35\s*/\s*минус\s+40[\s\S]{0,120}?плюс\s+(\d+)",
            text,
            re.IGNORECASE,
        )
        if m and out.get("tempAmbientMax") is None:
            out["tempAmbientMin"] = -40
            out["tempAmbientMax"] = int(m.group(1))

    if out.get("tempMediumMin") is not None or out.get("tempAmbientMin") is not None:
        out["temperature_unit"] = "°C"

    turbo_acc = out.get("accuracy")
    turbo_has_pct = isinstance(turbo_acc, str) and "%" in turbo_acc
    if not turbo_has_pct:
        acc = _extract_accuracy_from_ocr(text)
        if acc:
            out["accuracy"] = normalize_accuracy_value(acc)
        else:
            acc_range = _extract_accuracy_range_from_text(text)
            if acc_range:
                out["accuracy"] = acc_range
            else:
                m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
                if m and "погрешност" in low:
                    out["accuracy"] = m.group(1).replace(",", ".") + "%"

    gazprom_ufg = _extract_gazprom_ufg_scan_ol(text)
    for key, value in gazprom_ufg.items():
        if value is not None and not (isinstance(value, str) and not value.strip()):
            out[key] = value

    return _normalize_specs(out)


def _merge_specs(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    """primary перекрывает fallback; пустые значения берутся из fallback."""
    p = _normalize_specs(primary)
    f = _normalize_specs(fallback)

    def _empty(key: str, val: Any) -> bool:
        if val is None:
            return True
        if isinstance(val, str) and not val.strip():
            return True
        if key in ("flowMin", "flowMax", "pressureMin", "pressureMax", "tempMediumMin",
                   "tempMediumMax", "tempAmbientMin", "tempAmbientMax", "diameter"):
            if isinstance(val, (int, float)) and val == 0:
                return True
        return False

    merged = dict(p)
    for k in SPEC_KEYS:
        if _empty(k, merged.get(k)) and not _empty(k, f.get(k)):
            merged[k] = f[k]
    return _normalize_specs(merged)


SPEC_KEYS = [
    "medium",
    "gas_type",
    "duplication_type",
    "flowMin",
    "flowMax",
    "flow_unit",
    "pressureMin",
    "pressureMax",
    "pressure_unit",
    "tempMediumMin",
    "tempMediumMax",
    "tempAmbientMin",
    "tempAmbientMax",
    "temperature_unit",
    "accuracy",
    "diameter",
]

# Старые ключи (LLM/черновики) → актуальные
_SPEC_LEGACY_ALIASES = {
    "duplication": "duplication_type",
    "duplicationType": "duplication_type",
    "redundancy": "duplication_type",
    "redundancy_type": "duplication_type",
    "flow_min": "flowMin",
    "flow_max": "flowMax",
    "pressure_min": "pressureMin",
    "pressure_max": "pressureMax",
    "temperature_min": "tempMediumMin",
    "temperature_max": "tempMediumMax",
    "ambient_temp_min": "tempAmbientMin",
    "ambient_temp_max": "tempAmbientMax",
}


def _normalize_specs(data: Dict[str, Any]) -> Dict[str, Any]:
    src: Dict[str, Any] = dict(data or {})
    merged: Dict[str, Any] = {}
    for old, new in _SPEC_LEGACY_ALIASES.items():
        if src.get(old) is not None and src.get(new) is None:
            merged[new] = src.get(old)
    for k, v in src.items():
        if k in SPEC_KEYS:
            merged[k] = v
        elif k in _SPEC_LEGACY_ALIASES and merged.get(_SPEC_LEGACY_ALIASES[k]) is None:
            merged[_SPEC_LEGACY_ALIASES[k]] = v
    out: Dict[str, Any] = {}
    for k in SPEC_KEYS:
        value = merged.get(k)
        if k == "duplication_type":
            value = normalize_duplication_type(value)
        if k in (
            "flowMin",
            "flowMax",
            "pressureMin",
            "pressureMax",
            "tempMediumMin",
            "tempMediumMax",
            "tempAmbientMin",
            "tempAmbientMax",
            "diameter",
        ):
            value = _coerce_numeric_value(value)
        out[k] = value
    return out


DUPLICATION_NONE = "none"
DUPLICATION_PARTIAL = "partial"
DUPLICATION_FULL = "full"
DUPLICATION_DEFAULT = DUPLICATION_NONE
DUPLICATION_ALLOWED = (DUPLICATION_NONE, DUPLICATION_PARTIAL, DUPLICATION_FULL)
DUPLICATION_DISPLAY = {
    DUPLICATION_NONE: "без дублирования",
    DUPLICATION_PARTIAL: "частичное дублирование",
    DUPLICATION_FULL: "полное дублирование",
}


def normalize_duplication_type(value: Any) -> Optional[str]:
    """Нормализует тип дублирования расходомера к одному из трёх кодов."""
    if value is None:
        return None
    raw = str(value).strip().casefold().replace("ё", "е")
    raw = re.sub(r"[\s_/-]+", " ", raw).strip()
    if not raw or raw in {"null", "не указано", "не указан", "неизвестно", "-", "—", "n/a"}:
        return None
    if raw in {"none", "no", "without", "без", "нет", "отсутствует", "без дублирования"}:
        return DUPLICATION_NONE
    if "част" in raw or raw in {"partial", "partly"}:
        return DUPLICATION_PARTIAL
    if "полн" in raw or raw in {"full", "complete"}:
        return DUPLICATION_FULL
    if "без" in raw and ("дубли" in raw or "резерв" in raw):
        return DUPLICATION_NONE
    return None


def extract_duplication_type_from_text(text: str) -> Optional[str]:
    """Эвристика для опросных листов и свободного текста."""
    low = (text or "").casefold().replace("ё", "е")
    if not low:
        return None
    if re.search(r"полн\w*\s+(?:дублир|резервир)", low) or re.search(
        r"(?:дублир|резервир)[\w\s:.-]{0,40}полн", low
    ):
        return DUPLICATION_FULL
    if re.search(r"частич\w*\s+(?:дублир|резервир)", low) or re.search(
        r"(?:дублир|резервир)[\w\s:.-]{0,40}част", low
    ):
        return DUPLICATION_PARTIAL
    if re.search(r"(?:дубл|резерв).{0,160}(?:част|part)", low, re.DOTALL):
        return DUPLICATION_PARTIAL
    if re.search(r"(?:част|part).{0,160}(?:дубл|резерв)", low, re.DOTALL):
        return DUPLICATION_PARTIAL
    if re.search(r"(?:дубл|резерв).{0,160}(?:полн|full)", low, re.DOTALL):
        return DUPLICATION_FULL
    if re.search(r"комплект\s+из\s+двух", low) and re.search(r"dn\d+", low):
        return DUPLICATION_PARTIAL
    if re.search(r"резервирован\w*\s+измерител", low):
        return DUPLICATION_PARTIAL
    if re.search(
        r"количество\s+прибор\w*[^\d\n]{0,40}([2-9])",
        text or "",
        re.IGNORECASE,
    ):
        if re.search(r"опросный\s+лист\s+расходомера\s+cfm", text or "", re.IGNORECASE):
            return DUPLICATION_PARTIAL
        if re.search(r"опросный\s+лист\s+расходомера\s+ufl", text or "", re.IGNORECASE):
            return None
    if re.search(r"без\s+(?:дублир|резервир)", low) or re.search(
        r"(?:дублир|резервир)[\w\s:.-]{0,40}(?:нет|без|отсутств)", low
    ):
        return DUPLICATION_NONE
    return None


def _is_missing_accuracy(value: Any) -> bool:
    if value is None:
        return True
    s = str(value).strip().lower().rstrip(".,;:")
    return s in {"", "0", "null", "none", "не указано", "не указан", "неизвестно", "нет", "-", "—", "n/a", "na"}


def _normalize_accuracy_letter(value: str) -> str:
    s = str(value).strip().upper()
    return {"A": "А", "B": "В", "C": "С", "D": "Д"}.get(s, s)


def normalize_accuracy_value(value: Any) -> Any:
    if value is None:
        return None
    raw = str(value).strip()
    s = _normalize_accuracy_letter(raw)
    if _is_missing_accuracy(s):
        return None
    if "%" in raw and "-" in raw:
        range_m = re.search(
            r"(\d+(?:[.,]\d+)?)\s*%\s*[-–—]\s*(\d+(?:[.,]\d+)?)\s*%",
            raw,
            re.IGNORECASE,
        )
        if range_m:
            return (
                f"{range_m.group(1).replace(',', '.')}%-"
                f"{range_m.group(2).replace(',', '.')}%"
            )
    if len(raw) <= 2 and s in {"А", "Б"}:
        return "0,5%"
    if len(raw) <= 2 and s in {"В", "Г"}:
        return "1%"
    if "%" in raw:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", raw)
        if m:
            num = m.group(1)
            return f"{num}%" if "." in num else f"{num.replace('.', ',')}%"
    if re.fullmatch(r"\d+(?:[.,]\d+)?", s.replace(" ", "")):
        return raw.replace(".", ",") if "," in raw else raw
    return value


def _extract_accuracy_from_ocr(ocr_text: str) -> Optional[str]:
    text = ocr_text or ""
    patterns = [
        r"вариант\s+исполнения\s+по\s+точности\s+прибора[\s\S]{0,120}?([АAБBВVГGСC])",
        r"точности\s+прибора[\s\S]{0,120}?([АAБBВVГGСC])",
        r"класс\s+точности[\s:._-]*([АAБBВVГGСC]|\d+(?:[.,]\d+)?\s*%?)",
        r"точность[\s:._-]*([АAБBВVГGСC]|\d+(?:[.,]\d+)?\s*%?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return _normalize_accuracy_letter(m.group(1))
    return None


def _normalize_medium_value(value: Any) -> Any:
    from .medium_normalize import try_normalize_medium_value

    return try_normalize_medium_value(value)


def _postprocess_specs(specs: Dict[str, Any], ocr_text: str) -> Dict[str, Any]:
    out = _normalize_specs(specs)
    out["medium"] = _normalize_medium_value(out.get("medium"))
    text_duplication = extract_duplication_type_from_text(ocr_text)
    if text_duplication:
        out["duplication_type"] = text_duplication
    if out.get("medium") == "liquid":
        out["duplication_type"] = None
    elif out.get("duplication_type") == DUPLICATION_NONE:
        text_dup = extract_duplication_type_from_text(ocr_text)
        if text_dup and text_dup != DUPLICATION_NONE:
            out["duplication_type"] = text_dup
    if _is_missing_accuracy(out.get("accuracy")):
        accuracy = _extract_accuracy_from_ocr(ocr_text)
        if accuracy:
            out["accuracy"] = normalize_accuracy_value(accuracy)
        else:
            acc_range = _extract_accuracy_range_from_text(ocr_text)
            if acc_range:
                out["accuracy"] = acc_range
    else:
        out["accuracy"] = normalize_accuracy_value(out.get("accuracy"))
    out = _validate_and_sanitize_specs(out, ocr_text)
    return out


def _format_llm_error_for_user(exc: BaseException) -> str:
    """Короткое объяснение для пользователя; полный trace остаётся в логах."""
    raw = str(exc)
    low = raw.lower()
    if "model" in low and any(
        x in low for x in ("does not exist", "not found", "invalid_request_error", "unknown model")
    ):
        return (
            "LM Studio: в config.yaml в поле llm.model указано имя модели, которой нет в сервере. "
            "В LM Studio запустите Local Server, слева выберите загруженную модель — её ID (как в API) "
            "скопируйте в back/project/config.yaml → llm.model, перезапустите бэкенд."
        )
    if "connection" in low or "refused" in low or "connect" in low:
        return (
            f"Нет соединения с LM Studio (base_url в config). Проверьте, что сервер запущен и "
            f"доступен с машины, где крутится бэкенд. Технически: {raw[:200]}"
        )
    return raw[:800]


def _build_specs_extraction_prompt(document_text: str) -> Tuple[str, str]:
    """System + user промпт для извлечения JSON (yandexgpt в LM Studio требует явной задачи)."""
    llm_input = trim_text_for_llm(document_text)
    user_block = (
        llm_input if llm_input.strip() else "(текст из документа пустой или не распознан)"
    )
    schema_hint = (
        '{"medium":"gas","gas_type":"природный газ","duplication_type":"none","flowMin":3100,"flowMax":244000,'
        '"flow_unit":"ст.м³/ч","pressureMin":3.95,"pressureMax":7.35,"pressure_unit":"МПа",'
        '"tempMediumMin":-10,"tempMediumMax":30,"tempAmbientMin":-40,"tempAmbientMax":38,'
        '"temperature_unit":"°C","accuracy":"1%","diameter":300}'
    )
    system_content = (
        "Ты извлекаешь технические параметры расходомера из опросного листа или ТУ. "
        "Ответ — только один JSON-объект, без markdown и пояснений. "
        f"Ключи: {', '.join(SPEC_KEYS)}. "
        "Не добавляй другие ключи, вложенные объекты или таблицы состава газа. "
        "Состав газа нужен только для вывода medium/gas_type, сами компоненты не перечисляй. "
        'medium: "gas", "liquid" или "unknown". '
        'duplication_type — только для газового оборудования: "none" (без дублирования), '
        '"partial" (частичное дублирование) или "full" (полное дублирование). '
        'Если тип дублирования не указан — null, не придумывай. Для жидкости — null. '
        "tempMediumMin/Max — температура измеряемой среды; tempAmbientMin/Max — окружающей среды. "
        'temperature_unit — одна строка для всех четырёх температур. '
        'accuracy: "А"/"Б"/"В"/"Г" или проценты ("0.5%"), иначе null. '
        "Числа — number или null."
    )
    user_content = (
        "Извлеки параметры из текста опросного листа ниже. "
        "Верни ТОЛЬКО JSON по структуре примера (значения замени на найденные в тексте). "
        "Запрещено добавлять поля вне примера.\n"
        f"Пример структуры:\n{schema_hint}\n\n"
        f"Текст документа:\n---\n{user_block}\n---"
    )
    return system_content, user_content


def analyze_specs_with_llm(ocr_text: str, llm) -> Tuple[Dict[str, Any], str, float]:
    """
    Отправляет распознанный текст в LM Studio; ожидает один JSON-объект с полями SPEC_KEYS.
    При сбое LLM — эвристики по тексту документа.

    Returns:
        (specs, raw_llm_text, llm_elapsed_ms)
    """
    from .chatbot_core.llm_client import LLMClient
    from .order_specs_helpers import list_missing_fields

    heuristic = extract_specs_heuristic(ocr_text)
    full_len = len(ocr_text or "")
    system_content, user_content = _build_specs_extraction_prompt(ocr_text)

    max_tokens = min(1024, getattr(llm, "max_tokens", 1024))
    timeout = getattr(llm, "timeout", 120)

    logger.info(
        "LM Studio: извлечение полей (вход %s симв. из %s), base_url=%s model=%s",
        len(user_content),
        full_len,
        getattr(getattr(llm, "client", None), "base_url", "?"),
        getattr(llm, "model", "?"),
    )

    create_kwargs: Dict[str, Any] = {
        "model": llm.model,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "timeout": timeout,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
    }

    raw = ""
    llm_ms = 0.0
    data: Dict[str, Any] = {}

    t_llm = time.perf_counter()
    try:
        response = llm.client.chat.completions.create(**create_kwargs)
        llm_ms = _ms_elapsed(t_llm)
        if not response or not response.choices:
            raise RuntimeError("пустой ответ от LLM")
        msg = response.choices[0].message
        raw = LLMClient._extract_assistant_text(msg)
        if not raw.strip() and getattr(msg, "reasoning_content", None):
            raw = str(msg.reasoning_content or "").strip()
        logger.info(
            "LM Studio: ответ за %s ms (%s символов), парсинг JSON",
            llm_ms,
            len(raw or ""),
        )
        data = _parse_json_from_llm(raw)
        recovered = _parse_specs_pairs_from_llm(raw)
        for key in SPEC_KEYS:
            if data.get(key) is None and recovered.get(key) is not None:
                data[key] = recovered[key]
    except Exception as llm_err:
        llm_ms = _ms_elapsed(t_llm)
        recovered = _parse_specs_pairs_from_llm(raw)
        if recovered:
            data = recovered
            logger.warning(
                "LM Studio вернула невалидный JSON (%s); восстановлено %s полей по SPEC_KEYS",
                llm_err,
                sum(1 for v in recovered.values() if v is not None),
            )
        else:
            logger.warning("LM Studio извлечение не удалось: %s", llm_err)

    specs = _merge_specs(data, heuristic)
    specs = _postprocess_specs(specs, ocr_text)
    specs = _prefer_consistent_heuristic_ranges(specs, heuristic, ocr_text)

    missing = list_missing_fields(specs)
    if len(missing) > 6 and full_len > 500:
        logger.info(
            "После LLM+эвристик осталось %s пустых полей: %s",
            len(missing),
            missing[:8],
        )

    if not raw and not any(specs.get(k) is not None for k in SPEC_KEYS):
        raise RuntimeError("не удалось извлечь параметры из документа")

    return specs, raw, llm_ms


def _prefer_consistent_heuristic_ranges(
    specs: Dict[str, Any], heuristic: Dict[str, Any], ocr_text: str = ""
) -> Dict[str, Any]:
    """
    LLM иногда выбирает число из соседней строки таблицы как минимум расхода/давления.
    Эвристика надёжнее при расхождении масштаба (×50 и более).
    """
    out = _normalize_specs(specs)
    h = _normalize_specs(heuristic)

    for min_key, max_key in (("flowMin", "flowMax"), ("pressureMin", "pressureMax")):
        h_max = h.get(max_key)
        h_min = h.get(min_key)
        out_min = out.get(min_key)
        out_max = out.get(max_key)
        if h_max is not None and out_max is not None:
            try:
                h_f = float(h_max)
                out_f = float(out_max)
                if min_key == "flowMin" and h_f <= 10 and out_f > max(100.0, h_f * 20.0):
                    continue
                if h_f <= 10 and out_f > max(100.0, h_f * 20.0):
                    continue
                ratio = abs(out_f) / max(abs(h_f), 1e-9)
                if ratio > 50 or ratio < 0.02:
                    out[max_key] = h_max
                    if h_min is not None:
                        out[min_key] = h_min
                    elif out_min is not None and float(out_min) < float(h_max):
                        out[min_key] = None
                    continue
            except (TypeError, ValueError):
                pass
        if h_max is None or h_min is not None:
            continue
        if out_max is None or abs(float(out_max) - float(h_max)) > 1e-9:
            continue
        if out_min is not None and float(out_min) < float(h_max):
            out[min_key] = None

    for key in (
        "medium",
        "gas_type",
        "duplication_type",
        "flowMin",
        "flowMax",
        "flow_unit",
        "pressureMin",
        "pressureMax",
        "pressure_unit",
        "tempMediumMin",
        "tempMediumMax",
        "tempAmbientMin",
        "tempAmbientMax",
        "temperature_unit",
        "accuracy",
        "diameter",
    ):
        h_value = h.get(key)
        if h_value is None or (isinstance(h_value, str) and not h_value.strip()):
            continue
        if key == "duplication_type" and out.get("medium") == "liquid":
            continue
        out_value = out.get(key)
        if key == "medium":
            if isinstance(out_value, str) and len(out_value.strip()) > 12:
                continue
            out_norm = _normalize_medium_value(out_value)
            h_norm = _normalize_medium_value(h_value)
            if out_norm == "liquid" and h_norm == "gas":
                continue
        if key == "accuracy":
            if isinstance(out_value, str) and "%" in str(out_value):
                continue
            if isinstance(out_value, str) and out_value.strip().isdigit() and int(out_value) <= 10:
                if isinstance(h_value, str) and "%" in h_value:
                    continue
        if key in ("flowMin", "flowMax") and h_value is not None and out_value is not None:
            try:
                h_f = float(h_value)
                out_f = float(out_value)
                if h_f <= 10 and out_f > h_f * 8.0:
                    continue
                if key == "flowMin" and out_f >= 10 and h_f <= 10:
                    continue
            except (TypeError, ValueError):
                pass
        if out_value is None or out_value != h_value:
            out[key] = h_value

    return _validate_and_sanitize_specs(out, ocr_text)


def run_pdf_order_pipeline(
    attachment_abs_path: str, llm, *, skip_cache: bool = False
) -> Tuple[Dict[str, Any], str, str, str, Dict[str, Any]]:
    """
    Полный цикл: OCR → LLM → JSON.

    Returns:
        (specs_dict, ocr_text, error_message, llm_raw_response, timing) —
        error_message пустая строка при успехе;
        timing: {ocr_ms, llm_ms, pipeline_ms, ocr_chars}.
    """
    t_pipeline = time.perf_counter()
    err = ""
    ocr_text = ""
    llm_ms = 0.0
    file_hash = ""
    text_source = "pdf_ocr"
    if is_docx_attachment(attachment_abs_path):
        text_source = "docx"
    timing: Dict[str, Any] = {
        "ocr_ms": 0.0,
        "llm_ms": 0.0,
        "pipeline_ms": 0.0,
        "ocr_chars": 0,
        "llm_input_chars": 0,
        "text_source": text_source,
        "cache_hit": False,
    }

    try:
        file_hash = _file_sha256(attachment_abs_path)
        cached = None if skip_cache else _load_pipeline_cache(file_hash)
    except Exception:
        logger.exception("PDF pipeline cache lookup failed")
        cached = None

    if cached:
        specs = _normalize_specs(cached.get("specs") or {})
        ocr_text = str(cached.get("ocr_text") or "")
        err = str(cached.get("err") or "")
        llm_raw = str(cached.get("llm_raw") or "")
        cached_timing = cached.get("timing") if isinstance(cached.get("timing"), dict) else {}
        timing.update(cached_timing)
        timing["cache_hit"] = True
        timing["cached_ocr_ms"] = cached_timing.get("ocr_ms", 0)
        timing["cached_llm_ms"] = cached_timing.get("llm_ms", 0)
        timing["cached_pipeline_ms"] = cached_timing.get("pipeline_ms", 0)
        timing["ocr_ms"] = 0.0
        timing["llm_ms"] = 0.0
        timing["pipeline_ms"] = _ms_elapsed(t_pipeline)
        timing["ocr_chars"] = len(ocr_text or "")
        timing["llm_input_chars"] = len(trim_text_for_llm(ocr_text))
        logger.info(
            "[Чатбот заказ] PDF pipeline cache hit: %s символов, исходный пайплайн %s ms",
            timing["ocr_chars"],
            timing.get("cached_pipeline_ms"),
        )
        return specs, ocr_text, err, llm_raw, timing

    ext = os.path.splitext(attachment_abs_path)[1].lower()
    logger.info(
        "[Чатбот заказ] Старт извлечения текста (%s): %s",
        text_source,
        ext or "без расширения",
    )
    t_ocr = time.perf_counter()
    try:
        ocr_text, text_source = attachment_to_text(attachment_abs_path)
        timing["text_source"] = text_source
        timing["ocr_ms"] = _ms_elapsed(t_ocr)
        timing["ocr_chars"] = len(ocr_text or "")
        if ocr_text.strip():
            logger.info(
                "Извлечение текста (%s): %s символов за %s ms",
                text_source,
                timing["ocr_chars"],
                timing["ocr_ms"],
            )
        else:
            logger.warning(
                "Извлечение текста (%s): пустой результат",
                text_source,
            )
    except Exception as e:
        timing["ocr_ms"] = _ms_elapsed(t_ocr)
        logger.exception("Извлечение текста из вложения failed (%s)", text_source)
        err = f"{'DOCX' if text_source == 'docx' else 'OCR'}: {e}"
        ocr_text = ""

    logger.info(
        "[Чатбот заказ] Текст готов за %s ms (%s символов, %s); отправка в LM Studio",
        timing["ocr_ms"],
        timing["ocr_chars"],
        text_source,
    )
    llm_raw = ""
    specs: Dict[str, Any] = _normalize_specs({k: None for k in SPEC_KEYS})
    try:
        specs, llm_raw, llm_ms = analyze_specs_with_llm(ocr_text, llm)
        timing["llm_ms"] = llm_ms
        timing["llm_input_chars"] = len(trim_text_for_llm(ocr_text))
    except Exception as e:
        logger.exception("LLM specs extraction failed")
        llm_msg = _format_llm_error_for_user(e)
        if not err:
            err = llm_msg
        else:
            err = f"{err}; {llm_msg}"
        specs = _normalize_specs({k: None for k in SPEC_KEYS})
    finally:
        timing["pipeline_ms"] = _ms_elapsed(t_pipeline)
        try:
            _log_pdf_pipeline_timing(
                timing,
                prefix="[PDF timing]" if not err else "[PDF timing] (LLM error)",
            )
        except Exception:
            logger.exception("PDF timing log failed")

    if file_hash and (
        ocr_text.strip()
        or llm_raw.strip()
        or any(specs.get(k) is not None for k in SPEC_KEYS)
    ):
        _save_pipeline_cache(
            file_hash,
            {
                "specs": _normalize_specs(specs),
                "ocr_text": ocr_text,
                "err": err,
                "llm_raw": llm_raw,
                "timing": timing,
            },
        )

    return specs, ocr_text, err, llm_raw, timing

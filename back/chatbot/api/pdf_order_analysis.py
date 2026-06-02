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
PIPELINE_CACHE_VERSION = "order-specs-pdf-v4"

_PIPELINE_CACHE_DIR = os.path.normpath(
    os.environ.get(
        "ORDER_SPECS_PIPELINE_CACHE_DIR",
        os.path.join(os.path.dirname(__file__), "..", "media", "order_specs_cache"),
    )
)

# Строки с ключевыми словами для урезания текста перед LLM (полный текст — в postprocess)
_LLM_KEYWORD_RE = re.compile(
    r"(?i)(расход|давлен|температ|точност|диаметр|м[³3]/ч|мпа|кпа|бар|"
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


def _coerce_numeric_value(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        n = _parse_first_number(value)
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


def extract_specs_heuristic(document_text: str) -> Dict[str, Any]:
    """
    Извлечение полей из типового опросного листа (без LLM).
    Заполняет только то, что удалось надёжно найти в тексте.
    """
    text = document_text or ""
    low = text.lower()
    pattern_text = _normalize_ocr_for_patterns(text)
    out: Dict[str, Any] = {k: None for k in SPEC_KEYS}

    if re.search(r"природн\w*\s+газ", low) or "■" in text and "природный газ" in low:
        out["medium"] = "gas"
        out["gas_type"] = "природный газ"
    elif re.search(r"\bгаз\b", low) and "жидкост" not in low:
        out["medium"] = "gas"

    m = re.search(
        r"номинальн\w*\s+диаметр\s+арматур\w*[^\d]{0,40}(\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if m:
        out["diameter"] = int(m.group(1))

    m = re.search(
        r"номинальн\w*\s+давлен\w*[^\d]{0,30}(\d+(?:[.,]\d+)?)",
        text,
        re.IGNORECASE,
    )
    if m:
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
    if m:
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
    if block_m:
        a = _parse_first_number(re.sub(r"\s", "", str(block_m.group(1))))
        b = _parse_first_number(re.sub(r"\s", "", str(block_m.group(2))))
        if a is not None and b is not None:
            out["flowMin"] = int(min(a, b))
            out["flowMax"] = int(max(a, b))
            out["flow_unit"] = "ст.м³/ч"
    else:
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
            r"(?:внутренн\w*\s+диаметр\s+трубопровод\w*|номинальн\w*\s+диаметр|DN|ДУ)"
            r"[\s\S]{0,120}?(\d{2,4})",
            pattern_text,
            re.IGNORECASE,
        )
        if m:
            out["diameter"] = int(m.group(1))

    m = re.search(
        r"температур\w*\s+измеряем\w*\s+сред\w*[\s\S]{0,250}?min[^\d-]{0,30}(-?\d+)"
        r"[\s\S]{0,250}?max[^\d-]{0,30}(\+?\d+)",
        text,
        re.IGNORECASE,
    )
    if m:
        out["tempMediumMin"] = int(m.group(1))
        out["tempMediumMax"] = int(re.sub(r"\+", "", m.group(2)))

    m = re.search(
        r"температур\w*\s+рабоч\w*\s+сред\w*[\s\S]{0,120}?минимальн\w*[^\d-]{0,15}(-?\d+)"
        r"[\s\S]{0,120}?максимальн\w*[^\d-]{0,15}(\+?\d+)",
        text,
        re.IGNORECASE,
    )
    if m:
        out["tempMediumMin"] = int(m.group(1))
        out["tempMediumMax"] = int(re.sub(r"\+", "", m.group(2)))

    m = re.search(
        r"характеристик\w*\s+окружающ\w*\s+сред\w*[\s\S]{0,400}?минимальн\w*[^\d-]{0,30}(-?\d+)"
        r"[\s\S]{0,200}?максимальн\w*[^\d-]{0,30}(\+?\d+)",
        text,
        re.IGNORECASE,
    )
    if m:
        out["tempAmbientMin"] = int(m.group(1))
        out["tempAmbientMax"] = int(re.sub(r"\+", "", m.group(2)))
    else:
        m = re.search(
            r"минус\s+35\s*/\s*минус\s+40[\s\S]{0,120}?плюс\s+(\d+)",
            text,
            re.IGNORECASE,
        )
        if m:
            out["tempAmbientMin"] = -40
            out["tempAmbientMax"] = int(m.group(1))

    if out.get("tempMediumMin") is not None or out.get("tempAmbientMin") is not None:
        out["temperature_unit"] = "°C"

    acc = _extract_accuracy_from_ocr(text)
    if acc:
        out["accuracy"] = normalize_accuracy_value(acc)
    else:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
        if m and "погрешност" in low:
            out["accuracy"] = m.group(1).replace(",", ".") + "%"

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
    s = _normalize_accuracy_letter(str(value).strip())
    if _is_missing_accuracy(s):
        return None
    if s in {"А", "Б"}:
        return "0,5%"
    if s in {"В", "Г"}:
        return "1%"
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
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("gas", "liquid", "unknown"):
        return s
    if "жидк" in s or s == "liquid":
        return "liquid"
    if "газ" in s or "природн" in s or s == "газ":
        return "gas"
    return value


def _postprocess_specs(specs: Dict[str, Any], ocr_text: str) -> Dict[str, Any]:
    out = _normalize_specs(specs)
    out["medium"] = _normalize_medium_value(out.get("medium"))
    if _is_missing_accuracy(out.get("accuracy")):
        accuracy = _extract_accuracy_from_ocr(ocr_text)
        if accuracy:
            out["accuracy"] = normalize_accuracy_value(accuracy)
    else:
        out["accuracy"] = normalize_accuracy_value(out.get("accuracy"))
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
        '{"medium":"gas","gas_type":"природный газ","flowMin":3100,"flowMax":244000,'
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
    specs = _prefer_consistent_heuristic_ranges(specs, heuristic)

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


def _prefer_consistent_heuristic_ranges(specs: Dict[str, Any], heuristic: Dict[str, Any]) -> Dict[str, Any]:
    """
    LLM иногда выбирает число из соседней строки таблицы как минимум расхода/давления.
    Если эвристика нашла только верхний предел, а LLM добавила меньший минимум,
    оставляем максимум из эвристики как более надёжный и не придумываем минимум.
    """
    out = _normalize_specs(specs)
    h = _normalize_specs(heuristic)

    for min_key, max_key in (("flowMin", "flowMax"), ("pressureMin", "pressureMax")):
        h_max = h.get(max_key)
        h_min = h.get(min_key)
        out_min = out.get(min_key)
        out_max = out.get(max_key)
        if h_max is None or h_min is not None:
            continue
        if out_max is None or abs(float(out_max) - float(h_max)) > 1e-9:
            continue
        if out_min is not None and float(out_min) < float(h_max):
            out[min_key] = None

    return _normalize_specs(out)


def run_pdf_order_pipeline(
    attachment_abs_path: str, llm
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
        cached = _load_pipeline_cache(file_hash)
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

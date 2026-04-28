# -*- coding: utf-8 -*-
"""
Распознавание PDF через EasyOCR (рендер страниц через PyMuPDF) и извлечение
структурированных характеристик через LM Studio (OpenAI-совместимый API).
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Ленивая инициализация EasyOCR (тяжёлая загрузка моделей при первом вызове)
_easyocr_reader = None

MAX_PDF_PAGES = 15
OCR_ZOOM = 2.0
MAX_OCR_CHARS = 120_000


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr

        _easyocr_reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _easyocr_reader


def ocr_pdf_to_text(file_path: str) -> str:
    """Рендерит страницы PDF в изображения и распознаёт текст EasyOCR."""
    import fitz  # PyMuPDF

    reader = _get_easyocr_reader()
    texts: list[str] = []

    doc = fitz.open(file_path)
    try:
        n = min(len(doc), MAX_PDF_PAGES)
        for i in range(n):
            page = doc[i]
            mat = fitz.Matrix(OCR_ZOOM, OCR_ZOOM)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            arr = np.array(img)
            result = reader.readtext(arr)
            line = "\n".join(item[1] for item in result if item[1] and str(item[1]).strip())
            if line.strip():
                texts.append(line)
    finally:
        doc.close()

    combined = "\n\n".join(texts).strip()
    if len(combined) > MAX_OCR_CHARS:
        combined = combined[:MAX_OCR_CHARS]
    return combined


def _parse_json_from_llm(raw: str) -> Dict[str, Any]:
    """Достаёт JSON из ответа модели (в т.ч. обёрнутого в ```json)."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("пустой ответ LLM")
    if "```" in s:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
        if m:
            s = m.group(1).strip()
    s = s.strip()
    obj = json.loads(s)
    if not isinstance(obj, dict):
        raise ValueError("ожидался JSON-объект")
    return obj


SPEC_KEYS = [
    "medium",
    "gas_type",
    "flow_min",
    "flow_max",
    "flow_unit",
    "pressure_min",
    "pressure_max",
    "pressure_unit",
    "temperature_min",
    "temperature_max",
    "temperature_unit",
    "accuracy",
    "diameter",
]


def _normalize_specs(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in SPEC_KEYS:
        v = data.get(k)
        out[k] = v
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


def analyze_specs_with_llm(ocr_text: str, llm) -> Dict[str, Any]:
    """
    Отправляет распознанный текст в LM Studio; ожидает один JSON-объект с полями SPEC_KEYS.
    llm — экземпляр api.chatbot_core.llm_client.LLMClient.
    """
    schema_hint = """{
    "medium": "gas",
    "gas_type": "Природный газ",
    "flow_min": 10,
    "flow_max": 500,
    "flow_unit": "м³/ч",
    "pressure_min": 0.1,
    "pressure_max": 1.6,
    "pressure_unit": "МПа",
    "temperature_min": -40,
    "temperature_max": 60,
    "temperature_unit": "°C",
    "accuracy": "1-2%",
    "diameter": 100
}"""

    user_block = ocr_text if ocr_text.strip() else "(текст из PDF пустой или не распознан)"

    prompt = f"""Ты аналитик технических спецификаций. Ниже — текст, распознанный из PDF (OCR), возможны опечатки и обрывы.

Задача: по этому тексту извлечь параметры расходомера/учёта газа (или аналогичного оборудования), насколько это возможно.

Верни ТОЛЬКО один валидный JSON без комментариев и без текста до/после. Ключи строго как в примере структуры (типы: medium — строка, часто \"gas\"/\"liquid\"/\"unknown\"; gas_type — строка или null; flow_min/max, pressure_*, temperature_*, diameter — числа или null; *_unit и accuracy — строки).

Пример структуры (значения замени на извлечённые из текста; неизвестное — null):
{schema_hint}

Текст документа (OCR):
---
{user_block}
---
"""

    max_tokens = min(4096, getattr(llm, "max_tokens", 2048))
    timeout = getattr(llm, "timeout", 120)

    from .chatbot_core.llm_client import LLMClient

    logger.info(
        "LM Studio: запрос chat/completions (извлечение полей из PDF), base_url=%s model=%s",
        getattr(getattr(llm, "client", None), "base_url", "?"),
        getattr(llm, "model", "?"),
    )

    response = llm.client.chat.completions.create(
        model=llm.model,
        temperature=0.1,
        max_tokens=max_tokens,
        timeout=timeout,
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты возвращаешь только JSON-объект с заданными ключами. "
                    "Без Markdown, без пояснений, без Thinking Process."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )

    if not response or not response.choices:
        raise RuntimeError("пустой ответ от LLM")

    msg = response.choices[0].message
    raw = LLMClient._extract_assistant_text(msg)

    data = _parse_json_from_llm(raw)
    return _normalize_specs(data)


def run_pdf_order_pipeline(
    attachment_abs_path: str, llm
) -> Tuple[Dict[str, Any], str, str]:
    """
    Полный цикл: OCR → LLM → JSON.

    Returns:
        (specs_dict, ocr_text, error_message) — error_message пустая строка при успехе.
    """
    err = ""
    ocr_text = ""
    try:
        ocr_text = ocr_pdf_to_text(attachment_abs_path)
        if ocr_text.strip():
            logger.info("OCR PDF: получено %s символов текста", len(ocr_text))
        else:
            logger.warning("OCR PDF: текст пустой (страницы без распознавания или пустой файл)")
    except Exception as e:
        logger.exception("OCR PDF failed")
        err = f"OCR: {e}"
        ocr_text = ""

    try:
        specs = analyze_specs_with_llm(ocr_text, llm)
        return specs, ocr_text, ""
    except Exception as e:
        logger.exception("LLM specs extraction failed")
        llm_msg = _format_llm_error_for_user(e)
        if not err:
            err = llm_msg
        else:
            err = f"{err}; {llm_msg}"
        fallback = _normalize_specs({k: None for k in SPEC_KEYS})
        return fallback, ocr_text, err

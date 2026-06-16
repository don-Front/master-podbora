"""
Генерация PDF ТКП (краткое коммерческое предложение) для скачивания с клиента.
Требует: reportlab + TTF с кириллицей (Windows: arial.ttf; Linux: DejaVu).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

_TKP_DIR = Path(__file__).resolve().parent


def _project_base_dir() -> Path:
    return _TKP_DIR


def _find_cyrillic_font_path() -> Optional[str]:
    env = os.environ.get("TKP_PDF_FONT")
    if env and Path(env).is_file():
        return env
    candidates = [
        _project_base_dir() / "static" / "fonts" / "DejaVuSans.ttf",
        _project_base_dir() / "static" / "fonts" / "arial.ttf",
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\arialuni.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


class TkpPdfRequest(BaseModel):
    """Тело POST /api/tkp-pdf."""

    model_config = ConfigDict(populate_by_name=True)

    equipment_name: str = Field(
        ...,
        validation_alias=AliasChoices("equipment_name", "equipmentName"),
        description="Название прибора / позиции",
    )
    equipment_id: Optional[str] = Field(None, description="ID из каталога, напр. ufg2")
    price: Union[str, int, float] = Field(
        "по запросу",
        validation_alias=AliasChoices("price", "basePriceText", "base_price_text"),
        description="Прайс одной строкой или число",
    )
    phone: Optional[str] = None
    email: Optional[str] = None
    dn: Optional[Union[str, int, float]] = Field(
        None,
        validation_alias=AliasChoices("dn", "diameter", "recommended_diameter"),
        description="Диаметр условного прохода (Dn), мм",
    )
    temperature_max: Optional[Union[str, int, float]] = Field(
        None,
        validation_alias=AliasChoices(
            "temperature_max",
            "max_temperature",
            "temperature_max_c",
            "temperature",
        ),
        description="Максимальная температура, °C",
    )
    pressure_max_mpa: Optional[Union[str, int, float]] = Field(
        None,
        validation_alias=AliasChoices(
            "pressure_max_mpa",
            "pressure_max",
            "max_pressure",
            "pressure",
        ),
        description="Максимальное давление, МПа",
    )
    accuracy_percent: Optional[Union[str, int, float]] = Field(
        None,
        validation_alias=AliasChoices(
            "accuracy_percent",
            "accuracy",
            "accuracy_class",
            "accuracyClass",
        ),
        description="Класс точности (погрешность), %",
    )
    accessories: List[Any] = Field(
        default_factory=list,
        description="Список строк ИЛИ объектов {name, desc?, price?}",
    )
    organization: Optional[str] = None
    comment: Optional[str] = None
    tkp_number: Optional[str] = Field(None, description="Номер ТКП; если не передан — генерируется")
    valid_until: Optional[str] = Field(None, description="Срок действия, строкой")
    specs: Any = Field(
        default_factory=dict,
        description="Технические характеристики: объект {Название: значение} или массив {label, value}",
    )
    total_price: Optional[Union[str, int, float]] = Field(
        None, description="Итоговая цена; если не передана — считается из price + цен допов"
    )
    document_title: str = Field(
        "Технико-коммерческое предложение",
        description="Заголовок в шапке PDF",
    )

    @field_validator("accessories", mode="before")
    @classmethod
    def _coerce_accessories(cls, v: Any) -> List[Any]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [v]
        return v


def _normalize_accessories(raw: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append({"name": s, "desc": None, "price": None})
            continue
        if isinstance(item, dict):
            name = str(
                item.get("name")
                or item.get("title")
                or item.get("label")
                or ""
            ).strip()
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "desc": item.get("desc") or item.get("description"),
                    "price": item.get("price"),
                }
            )
    return out


def _normalize_specs(raw: Any) -> List[Dict[str, str]]:
    if isinstance(raw, list):
        out = []
        for item in raw:
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("name") or item.get("key") or "").strip()
                value = item.get("value")
                if label:
                    out.append({"label": label, "value": str(value if value is not None else "—")})
        return out
    if isinstance(raw, dict):
        return [{"label": str(k), "value": str(v)} for k, v in raw.items()]
    return []


def _spec_exists(rows: List[Dict[str, str]], needles: List[str]) -> bool:
    normalized = [
        re.sub(r"\s+", " ", row.get("label", "").strip().lower())
        for row in rows
    ]
    return any(any(needle in label for needle in needles) for label in normalized)


def _append_spec_if_missing(
    rows: List[Dict[str, str]],
    label: str,
    value: Optional[Union[str, int, float]],
    needles: List[str],
) -> None:
    if value is None or value == "" or _spec_exists(rows, needles):
        return
    rows.append({"label": label, "value": str(value)})


def _format_accuracy(value: Optional[Union[str, int, float]]) -> Optional[str]:
    if value is None or value == "":
        return None
    s = str(value).strip()
    if "%" in s or "±" in s:
        return s
    return f"± {s} %"


def _format_price(p: Any) -> str:
    if p is None:
        return "—"
    if isinstance(p, (int, float)):
        if p == int(p):
            return f"{int(p):,}".replace(",", " ") + " ₽"
        return f"{p:,.2f}".replace(",", " ") + " ₽"
    return str(p)


def _price_to_number(p: Any) -> Optional[float]:
    if p is None or p == "":
        return None
    if isinstance(p, (int, float)):
        return float(p)
    s = str(p)
    m = re.search(r"\d+", re.sub(r"\D", "", s))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _safe_filename(name: str) -> str:
    s = re.sub(r'[^\w\-]+', "_", name, flags=re.UNICODE).strip("_")
    return (s[:80] or "tkp") + ".pdf"


def build_tkp_pdf_bytes(body: TkpPdfRequest) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as e:
        raise RuntimeError(
            "Для генерации PDF установите пакет: pip install reportlab"
        ) from e

    font_path = _find_cyrillic_font_path()
    if not font_path:
        raise RuntimeError(
            "Не найден TTF со шрифтом с кириллицей. "
            "Положите DejaVuSans.ttf в static/fonts/ или задайте переменную окружения TKP_PDF_FONT."
        )

    font_name = "TKPCyrillic"
    pdfmetrics.registerFont(TTFont(font_name, font_path))
    bold_font_name = font_name
    for bp in (
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ):
        if bp.is_file():
            bold_font_name = "TKPCyrillicBold"
            pdfmetrics.registerFont(TTFont(bold_font_name, str(bp)))
            break

    acc = _normalize_accessories(body.accessories)
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 14 * mm
    right = width - 14 * mm
    top = height - 14 * mm
    bottom = 14 * mm
    blue = colors.HexColor("#0D3B66")
    light_blue = colors.HexColor("#f1f5f9")
    pale_blue = colors.HexColor("#f8fafc")
    border = colors.HexColor("#cbd5e1")
    red = colors.HexColor("#c8102e")
    green = colors.HexColor("#28a745")

    def set_font(size: int = 9, bold: bool = False, color=colors.black) -> None:
        c.setFillColor(color)
        c.setFont(bold_font_name if bold else font_name, size)

    def draw_text(x: float, y: float, text: Any, size: int = 9, bold: bool = False, color=colors.black) -> None:
        set_font(size, bold, color)
        c.drawString(x, y, str(text))

    def draw_right(x: float, y: float, text: Any, size: int = 9, bold: bool = False, color=colors.black) -> None:
        set_font(size, bold, color)
        c.drawRightString(x, y, str(text))

    def wrap_text(text: Any, max_width: float, size: int = 9, bold: bool = False) -> List[str]:
        words = str(text or "").replace("\n", " ").split()
        if not words:
            return [""]
        f = bold_font_name if bold else font_name
        lines: List[str] = []
        cur = ""
        for word in words:
            probe = word if not cur else f"{cur} {word}"
            if pdfmetrics.stringWidth(probe, f, size) <= max_width:
                cur = probe
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def draw_wrapped(x: float, y: float, text: Any, max_width: float, size: int = 9, bold: bool = False) -> float:
        for line in wrap_text(text, max_width, size, bold):
            draw_text(x, y, line, size=size, bold=bold)
            y -= size * 1.35
        return y

    def draw_header() -> float:
        y = top
        header_img = _project_base_dir() / "static" / "images" / "tkp-header.png"
        if header_img.is_file():
            c.drawImage(str(header_img), left, y - 28 * mm, width=right - left, height=28 * mm, preserveAspectRatio=True, anchor="n")
        else:
            set_font(19, True, colors.HexColor("#4a4a4a"))
            c.drawString(left + 10 * mm, y - 15 * mm, "ТД")
            draw_text(left + 25 * mm, y - 9 * mm, "ТУРБУЛЕНТНОСТЬ", 13, True, colors.HexColor("#4a4a4a"))
            draw_text(left + 25 * mm, y - 15 * mm, "ДОН  группа компаний", 8, False, colors.HexColor("#4a4a4a"))
            draw_text(left + 86 * mm, y - 5 * mm, "Группа компаний «Турбулентность-ДОН»", 7, True)
            draw_text(left + 86 * mm, y - 9 * mm, "www.turbo-don.ru  e-mail: info@turbo-don.ru", 7)
            draw_text(left + 86 * mm, y - 13 * mm, "Тел. (863) 203-77-80", 7)
            draw_text(left + 86 * mm, y - 17 * mm, "344068, г. Ростов-на-Дону, ул. Вавилова, 73/7", 7)
        c.setStrokeColor(blue)
        c.setLineWidth(2)
        c.line(left, y - 33 * mm, right, y - 33 * mm)
        return y - 43 * mm

    def ensure_space(y: float, need: float) -> float:
        if y - need >= bottom:
            return y
        c.showPage()
        return draw_header()

    def section_title(y: float, title: str) -> float:
        y = ensure_space(y, 12 * mm)
        draw_text(left, y, title.upper(), 11, True, blue)
        c.setStrokeColor(border)
        c.line(left, y - 2.5 * mm, right, y - 2.5 * mm)
        return y - 7 * mm

    def draw_table(y: float, headers: List[str], rows: List[List[Any]], widths: List[float]) -> float:
        row_base = 7 * mm
        x_positions = [left]
        for w in widths[:-1]:
            x_positions.append(x_positions[-1] + w)
        table_w = sum(widths)

        def draw_row(y0: float, cells: List[Any], header: bool = False) -> float:
            wrapped = [
                wrap_text(cell, widths[i] - 4 * mm, 8, header)
                for i, cell in enumerate(cells)
            ]
            row_h = max(row_base, max(len(w) for w in wrapped) * 3.8 * mm + 3 * mm)
            y_top = y0
            y_bottom = y0 - row_h
            c.setFillColor(blue if header else (pale_blue if (draw_row.row_i % 2 == 1) else colors.white))
            c.rect(left, y_bottom, table_w, row_h, fill=1, stroke=0)
            c.setStrokeColor(blue if header else border)
            c.rect(left, y_bottom, table_w, row_h, fill=0, stroke=1)
            xx = left
            for w in widths[:-1]:
                xx += w
                c.line(xx, y_bottom, xx, y_top)
            for i, lines in enumerate(wrapped):
                ty = y_top - 4.2 * mm
                for line in lines:
                    color = colors.white if header else (blue if i == len(cells) - 1 else colors.black)
                    if i == len(cells) - 1:
                        draw_right(x_positions[i] + widths[i] - 2 * mm, ty, line, 8, header or i == len(cells) - 1, color)
                    else:
                        draw_text(x_positions[i] + 2 * mm, ty, line, 8, header, color)
                    ty -= 3.8 * mm
            draw_row.row_i += 1
            return y_bottom

        draw_row.row_i = 0  # type: ignore[attr-defined]
        y = ensure_space(y, row_base * 2)
        y = draw_row(y, headers, True)
        for row in rows:
            y = ensure_space(y, row_base * 2)
            y = draw_row(y, row)
        return y - 4 * mm

    def draw_specs_table(y: float, rows: List[Dict[str, str]]) -> float:
        w1, w2 = 82 * mm, (right - left) - 82 * mm
        row_base = 7 * mm
        for idx, row in enumerate(rows):
            label_lines = wrap_text(row["label"], w1 - 4 * mm, 8, True)
            value_lines = wrap_text(row["value"], w2 - 4 * mm, 8)
            row_h = max(row_base, max(len(label_lines), len(value_lines)) * 3.8 * mm + 3 * mm)
            y = ensure_space(y, row_h + 1 * mm)
            y_top, y_bottom = y, y - row_h
            c.setFillColor(pale_blue if idx % 2 == 1 else colors.white)
            c.rect(left, y_bottom, w1 + w2, row_h, fill=1, stroke=0)
            c.setFillColor(light_blue)
            c.rect(left, y_bottom, w1, row_h, fill=1, stroke=0)
            c.setStrokeColor(border)
            c.rect(left, y_bottom, w1 + w2, row_h, fill=0, stroke=1)
            c.line(left + w1, y_bottom, left + w1, y_top)
            ty = y_top - 4.2 * mm
            for line in label_lines:
                draw_text(left + 2 * mm, ty, line, 8, True, colors.HexColor("#334155"))
                ty -= 3.8 * mm
            ty = y_top - 4.2 * mm
            for line in value_lines:
                draw_text(left + w1 + 2 * mm, ty, line, 8)
                ty -= 3.8 * mm
            y = y_bottom
        return y - 4 * mm

    now = datetime.now()
    valid_until = body.valid_until or (now + timedelta(days=1)).strftime("%d.%m.%Y %H:%M")
    number = body.tkp_number or f"ТКП-{now.strftime('%Y%m%d')}-{now.strftime('%H%M')}"
    base_price_number = _price_to_number(body.price) or 0
    accessories_sum = sum(_price_to_number(row.get("price")) or 0 for row in acc)
    has_request = any((_price_to_number(row.get("price")) or 0) <= 0 for row in acc)
    explicit_total = _price_to_number(body.total_price)
    total = explicit_total if explicit_total is not None else (base_price_number + accessories_sum)

    y = draw_header()
    title = body.document_title.upper()
    title_w = pdfmetrics.stringWidth(title, bold_font_name, 16)
    draw_text((width - title_w) / 2, y, title, 16, True, blue)
    y -= 9 * mm

    meta_w = right - left - 8 * mm
    meta_blocks = [
        ("№ " + number, blue, False),
        (f"Дата формирования: {now.strftime('%d.%m.%Y %H:%M')}", blue, True),
        (f"Действительно до: {valid_until}", red, True),
    ]
    meta_wrapped: List[List[str]] = []
    for text, _color, bold in meta_blocks:
        meta_wrapped.append(wrap_text(text, meta_w, 8, bold))
    meta_line_step = 4.5 * mm
    meta_pad_v = 4 * mm
    meta_h = meta_pad_v * 2 + sum(max(1, len(lines)) for lines in meta_wrapped) * meta_line_step
    meta_top = y
    meta_bottom = y - meta_h
    c.setFillColor(light_blue)
    c.roundRect(left, meta_bottom, right - left, meta_h, 2 * mm, stroke=0, fill=1)
    c.setStrokeColor(border)
    c.roundRect(left, meta_bottom, right - left, meta_h, 2 * mm, stroke=1, fill=0)
    ty = meta_top - meta_pad_v - 3.5 * mm
    for lines, (_t, color, bold) in zip(meta_wrapped, meta_blocks):
        for line in lines:
            draw_text(left + 4 * mm, ty, line, 8, bold, color)
            ty -= meta_line_step
    y = meta_bottom - 6 * mm

    contact_w = right - left - 8 * mm
    email_lines = wrap_text(f"E-mail клиента: {body.email or '—'}", contact_w, 8, True)
    phone_lines = wrap_text(f"Телефон: {body.phone or '—'}", contact_w, 8, True)
    contact_line_step = 4.5 * mm
    contact_pad_v = 3 * mm
    contact_h = contact_pad_v * 2 + (len(email_lines) + len(phone_lines)) * contact_line_step
    contact_top = y
    contact_bottom = y - contact_h
    c.setFillColor(pale_blue)
    c.rect(left, contact_bottom, right - left, contact_h, fill=1, stroke=0)
    c.setFillColor(green)
    c.rect(left, contact_bottom, 3, contact_h, fill=1, stroke=0)
    ty = contact_top - contact_pad_v - 3.5 * mm
    for line in email_lines:
        draw_text(left + 4 * mm, ty, line, 8, True, blue)
        ty -= contact_line_step
    for line in phone_lines:
        draw_text(left + 4 * mm, ty, line, 8, True, blue)
        ty -= contact_line_step
    y = contact_bottom - 4 * mm

    y = section_title(y, "1. Основное оборудование")
    y = draw_table(
        y,
        ["№", "Наименование", "Стоимость, ₽"],
        [["1", body.equipment_name, _format_price(body.price)]],
        [10 * mm, 128 * mm, 42 * mm],
    )

    specs_rows = _normalize_specs(body.specs)
    equip_type = body.equipment_id or ""
    equip_type_label = {
        "ufg-f-v": "Turbo Flow UFG-F-V (ультразвуковой, газ)",
        "ufg2": "Turbo Flow UFG-F-V (ультразвуковой, газ)",
        "ufg-f-c": "Turbo Flow UFG-F-C (ультразвуковой, газ)",
        "ufgfc": "Turbo Flow UFG-F-C (ультразвуковой, газ)",
        "ufg-h": "Turbo Flow UFG-H (ультразвуковой, газ)",
        "ufl": "Turbo Flow UFL (ультразвуковой, жидкость)",
        "tfg-sf": "Turbo Flow TFG-SF (термоанемометрический, газ)",
        "tfgs1": "Turbo Flow TFG-SF (термоанемометрический, газ)",
        "tfg-hf": "Turbo Flow TFG-HF (термоанемометрический, газ)",
        "tfgh1": "Turbo Flow TFG-HF (термоанемометрический, газ)",
        "cfm": "Turbo Flow CFM (кориолисовый)",
        "spu5": "СПУ-5 (стационарная поверочная установка)",
    }.get(equip_type.lower())
    if not specs_rows:
        specs_rows = []
        if equip_type_label:
            specs_rows.append({"label": "Тип прибора", "value": equip_type_label})
        specs_rows.append({"label": "Параметры", "value": "согласно названию прибора"})
    _append_spec_if_missing(
        specs_rows,
        "Диаметр условного прохода (Dn), мм",
        body.dn,
        ["диаметр условного прохода", "dn"],
    )
    _append_spec_if_missing(
        specs_rows,
        "Максимальная температура, °C",
        body.temperature_max,
        ["максимальная температура", "температура"],
    )
    _append_spec_if_missing(
        specs_rows,
        "Максимальное давление, МПа",
        body.pressure_max_mpa,
        ["максимальное давление", "рабочее давление", "pраб", "давление"],
    )
    _append_spec_if_missing(
        specs_rows,
        "Класс точности (погрешность), %",
        _format_accuracy(body.accuracy_percent),
        ["класс точности", "погрешность", "accuracy"],
    )
    y = section_title(y, "2. Технические характеристики")
    y = draw_specs_table(y, specs_rows)

    if acc:
        y = section_title(y, "3. Дополнительные комплектующие")
        rows = []
        for i, row in enumerate(acc, start=1):
            price_num = _price_to_number(row.get("price")) or 0
            price = _format_price(price_num) if price_num > 0 else "по запросу"
            rows.append([str(i), row["name"], price])
        y = draw_table(y, ["№", "Наименование", "Стоимость, ₽"], rows, [10 * mm, 128 * mm, 42 * mm])

    y = ensure_space(y, 30 * mm)
    box_h = 30 * mm
    c.setFillColor(pale_blue)
    c.roundRect(left, y - box_h, right - left, box_h, 3 * mm, stroke=0, fill=1)
    c.setStrokeColor(blue)
    c.setLineWidth(2)
    c.roundRect(left, y - box_h, right - left, box_h, 3 * mm, stroke=1, fill=0)
    yy = y - 8 * mm
    draw_text(left + 5 * mm, yy, "Стоимость основного оборудования:", 9)
    draw_right(right - 5 * mm, yy, _format_price(base_price_number) if base_price_number > 0 else str(body.price), 9, False, blue)
    if acc:
        yy -= 7 * mm
        draw_text(left + 5 * mm, yy, "Стоимость доп. комплектующих:", 9)
        acc_text = (_format_price(accessories_sum) if accessories_sum > 0 else "по запросу") + (" + по запросу" if accessories_sum > 0 and has_request else "")
        draw_right(right - 5 * mm, yy, acc_text, 9, False, blue)
    yy -= 10 * mm
    c.setStrokeColor(blue)
    c.setLineWidth(1)
    c.line(left + 5 * mm, yy + 5 * mm, right - 5 * mm, yy + 5 * mm)
    draw_text(left + 5 * mm, yy, "ИТОГО:", 14, True, red)
    if body.total_price is not None:
        total_text = _format_price(body.total_price)
    elif base_price_number > 0:
        total_text = _format_price(total) + (" + по запросу" if has_request else "")
    else:
        total_text = f"от {_format_price(accessories_sum)} (базовая цена — по запросу)" if accessories_sum > 0 else "по запросу"
    draw_right(right - 5 * mm, yy, total_text, 14, True, red)
    y -= box_h + 7 * mm

    note = (
        body.comment
        or "Настоящее технико-коммерческое предложение носит информационный характер. "
        "Указанная стоимость является предварительной и может быть скорректирована "
        "в зависимости от окончательной комплектации, объёма заказа, условий поставки, "
        "сроков изготовления, а также индивидуальных требований заказчика."
    )
    validity = (
        "Настоящее предложение действительно в течение 24 (двадцати четырёх) часов "
        "с момента формирования"
    )
    footer_note = (
        "Для подтверждения заказа, согласования технических требований и получения "
        "развёрнутого коммерческого предложения обратитесь к нашему менеджеру по контактам, "
        "указанным в шапке документа. Благодарим за интерес к продукции «Турбулентность-ДОН»!"
    )
    note_w = right - left - 8 * mm
    note_lines = wrap_text(note, note_w, 7)
    validity_lines = wrap_text(validity, note_w - 6 * mm, 8, True)
    footer_lines = wrap_text(footer_note, note_w - 6 * mm, 7)
    line_h7 = 7 * 1.35
    line_h8 = 8 * 1.35
    note_pad_top = 6 * mm
    note_pad_bottom = 6 * mm
    gap_before_validity = 4 * mm
    dash_sep_h = 2.5 * mm
    gap_text_after_dash = 2.5 * mm
    gap_text_before_dash = 2.5 * mm
    gap_after_validity = 3 * mm
    validity_section_h = (
        gap_before_validity
        + dash_sep_h
        + gap_text_after_dash
        + len(validity_lines) * line_h8
        + gap_text_before_dash
        + dash_sep_h
        + gap_after_validity
    )
    note_h = (
        note_pad_top
        + len(note_lines) * line_h7
        + validity_section_h
        + len(footer_lines) * line_h7
        + note_pad_bottom
    )
    y = ensure_space(y, note_h + 4 * mm)
    note_top = y
    note_bottom = y - note_h
    c.setFillColor(colors.HexColor("#fff8e1"))
    c.roundRect(left, note_bottom, right - left, note_h, 2 * mm, stroke=0, fill=1)
    c.setStrokeColor(colors.HexColor("#f1c40f"))
    c.roundRect(left, note_bottom, right - left, note_h, 2 * mm, stroke=1, fill=0)
    yy = note_top - note_pad_top
    for line in note_lines:
        draw_text(left + 4 * mm, yy, line, 7)
        yy -= line_h7
    yy -= gap_before_validity

    def draw_dash_separator(y_pos: float) -> None:
        c.setStrokeColor(red)
        c.setDash(2, 2)
        c.line(left + 4 * mm, y_pos, right - 4 * mm, y_pos)
        c.setDash()

    draw_dash_separator(yy - dash_sep_h * 0.5)
    yy -= dash_sep_h + gap_text_after_dash
    for line in validity_lines:
        draw_text(left + 4 * mm, yy, line, 8, True, red)
        yy -= line_h8
    yy -= gap_text_before_dash
    draw_dash_separator(yy - dash_sep_h * 0.5)
    yy -= dash_sep_h + gap_after_validity
    for line in footer_lines:
        draw_text(left + 4 * mm, yy, line, 7)
        yy -= line_h7
    y = note_bottom - 12 * mm

    y = ensure_space(y, 18 * mm)
    draw_text(left, y, "Исполнитель:", 8, True)
    draw_text(left + 105 * mm, y, "Заказчик:", 8, True)
    c.line(left, y - 11 * mm, left + 80 * mm, y - 11 * mm)
    c.line(left + 105 * mm, y - 11 * mm, right, y - 11 * mm)
    draw_text(left + 7 * mm, y - 16 * mm, "подпись / ФИО / должность", 6, color=colors.grey)
    draw_text(left + 112 * mm, y - 16 * mm, "подпись / ФИО / должность", 6, color=colors.grey)

    c.save()
    data = buffer.getvalue()
    buffer.close()
    return data


def tkp_pdf_attachment_filename(body: TkpPdfRequest) -> str:
    """Предлагаемое имя загрузки (может содержать кириллицу)."""
    return _safe_filename(body.equipment_name or "tkp")


def tkp_pdf_discovery() -> Dict[str, Any]:
    return {
        "status": "ok",
        "message": "Отправьте POST с JSON телом TkpPdfRequest (см. /docs). В ответе — файл application/pdf.",
        "post_paths": ["/api/tkp-pdf", "/api/tkp_pdf"],
        "example_body": {
            "equipment_name": "Расходомер Turbo Flow UFG…",
            "equipment_id": "ufg2",
            "price": 125000,
            "phone": "+7…",
            "email": "client@example.com",
            "dn": 100,
            "temperature_max": 80,
            "pressure_max_mpa": 1.6,
            "accuracy_percent": 1.0,
            "accessories": [
                {"name": "Комплект монтажных частей", "desc": "КМЧ", "price": 4697},
                "Кабель связи RS-485",
            ],
        },
    }

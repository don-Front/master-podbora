"""Уведомления менеджеру о запросах цены и ТКП."""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime
from typing import Any, Iterable, List, Optional, Tuple

from email_templates import (
    BRAND_CARD_BG,
    BRAND_MUTED,
    BRAND_NAVY,
    BRAND_NAVY_LIGHT,
    BRAND_ORANGE,
    FONT,
    esc as _esc,
    load_logo_bytes as _load_logo_bytes,
    navy_panel_html,
    panel_html,
    row_html,
    send_branded_email,
    tkp_open_button_html,
    tkp_plain_link_html,
    widget_email,
)

logger = logging.getLogger(__name__)

try:
    from email_config import MANAGER_EMAIL
except ImportError:
    MANAGER_EMAIL = "d.shamray@turbo-don.ru"

SOURCE_SELECTION_MASTER = "selection_master"
SOURCE_CHATBOT = "chatbot"

SOURCE_LABELS = {
    SOURCE_SELECTION_MASTER: "Мастер подбора",
    SOURCE_CHATBOT: "Чатбот API",
}

SOURCE_HINTS = {
    SOURCE_SELECTION_MASTER: "turbo-podbor.ru",
    SOURCE_CHATBOT: "внешний API",
}


def normalize_source(source: Optional[str]) -> str:
    if source == SOURCE_CHATBOT:
        return SOURCE_CHATBOT
    return SOURCE_SELECTION_MASTER


def normalize_client_fio(value: Optional[str]) -> str:
    return (value or "").strip()


def _split_specs_text(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) > 1:
        return parts
    found = re.findall(
        r"(DN\s*\d+|\d+\s*луч[аи]?|[\d.,]+\s*МПа|[\d.,]+\s*[–\-]\s*[\d.,]+\s*%?)",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = [p.strip() for p in found if p.strip()]
    return cleaned if cleaned else [text]


def _parse_equipment_display(equipment_name: str) -> Tuple[str, List[str]]:
    name = (equipment_name or "").strip()
    specs: List[str] = []
    for part in re.findall(r"\(([^)]+)\)", name):
        for piece in _split_specs_text(part):
            if piece not in specs:
                specs.append(piece)
    base = re.sub(r"\s*\([^)]*\)", "", name).strip()
    return base or name, specs


def _spec_chip_cell(spec: str) -> str:
    return f"""
<td valign="top" style="padding:0 8px 8px 0;font-family:{FONT};">
  <table role="presentation" cellpadding="0" cellspacing="0"
         style="border-collapse:separate;border-spacing:0;">
    <tr>
      <td bgcolor="#EEF2F6" style="background-color:#EEF2F6;border:1px solid #D8DEE6;
          border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;color:{BRAND_NAVY};
          line-height:1.35;white-space:nowrap;">{_esc(spec)}</td>
    </tr>
  </table>
</td>"""


def _spec_chips_html(specs: List[str]) -> str:
    if not specs:
        return ""
    rows: List[str] = []
    chunk_size = 2
    for i in range(0, len(specs), chunk_size):
        chunk = specs[i : i + chunk_size]
        cells = "".join(_spec_chip_cell(s) for s in chunk)
        rows.append(f"<tr>{cells}</tr>")
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:10px;">
  {"".join(rows)}
</table>"""


def _source_block(source: str) -> str:
    label = SOURCE_LABELS[normalize_source(source)]
    hint = SOURCE_HINTS[normalize_source(source)]
    return f"""
═══════════════════════════════════════
ИСТОЧНИК
═══════════════════════════════════════
Действие выполнено через: {label} ({hint})
"""


def format_accessories_for_email(accessories: Iterable[Any]) -> List[str]:
    lines: List[str] = []
    for item in accessories or []:
        if isinstance(item, str):
            lines.append(item)
            continue
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("label") or "—")
            price = item.get("price")
            if price is None or price == "":
                lines.append(f"{name} (по запросу)")
            else:
                try:
                    num = int(float(price))
                    formatted = f"{num:,}".replace(",", " ")
                    lines.append(f"{name} ({formatted} ₽)")
                except (TypeError, ValueError):
                    lines.append(f"{name} ({price})")
            continue
        lines.append(str(item))
    return lines


def _contact_row_plain(label: str, value: str) -> str:
    return f"{label}: {value or '—'}"


def _text_value_html(value: str, *, link_prefix: str = "") -> str:
    clean = (value or "").strip()
    if not clean:
        return f'<span style="color:{BRAND_MUTED};font-size:13px;">—</span>'
    if link_prefix == "tel:":
        return (
            f'<a href="tel:{_esc(clean)}" style="color:{BRAND_NAVY};text-decoration:none;'
            f'font-size:13px;font-weight:600;">{_esc(clean)}</a>'
        )
    if link_prefix == "mailto:":
        return (
            f'<a href="mailto:{_esc(clean)}" style="color:{BRAND_NAVY};text-decoration:none;'
            f'font-size:13px;font-weight:600;">{_esc(clean)}</a>'
        )
    return f'<span style="color:{BRAND_NAVY};font-size:13px;font-weight:600;">{_esc(clean)}</span>'


def _contact_cell(label: str, value_html: str) -> str:
    return f"""
<td width="33%" valign="top" style="padding:0 4px;font-family:{FONT};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="border-collapse:separate;border-spacing:0;">
    <tr>
      <td style="background-color:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;padding:10px 12px;">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;
            color:{BRAND_MUTED};margin-bottom:4px;">{_esc(label)}</div>
        {value_html}
      </td>
    </tr>
  </table>
</td>"""


def _build_html_email(
    *,
    headline: str,
    subheadline: str,
    source: str,
    equipment_name: str,
    price: str,
    phone: str,
    email_addr: str,
    client_fio: str = "",
    accessories_lines: Optional[List[str]] = None,
    action_hint: Optional[str] = None,
    tkp_url: Optional[str] = None,
    demo_badge: bool = False,
    logo_use_cid: bool = False,
) -> str:
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    src = normalize_source(source)
    model_name, specs = _parse_equipment_display(equipment_name)
    badge = "Запрос ТКП" if action_hint else "Запрос цены"

    price_inner = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td style="font-size:10px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;
        color:rgba(255,255,255,0.85);">Предварительная стоимость</td>
    <td align="right" style="font-size:10px;color:rgba(255,255,255,0.7);">НДС 22%</td>
  </tr>
  <tr>
    <td colspan="2" style="font-size:28px;font-weight:700;padding-top:4px;line-height:1.15;">{_esc(price)}</td>
  </tr>
</table>"""

    tkp_btn = tkp_open_button_html(tkp_url) if tkp_url else ""
    if tkp_url:
        model_block = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    <td valign="top" style="padding-right:8px;">
      <div style="font-size:17px;font-weight:700;color:{BRAND_NAVY};line-height:1.3;">{_esc(model_name)}</div>
    </td>
    <td valign="top" align="right" width="118">{tkp_btn}</td>
  </tr>
</table>"""
    else:
        model_block = (
            f'<div style="font-size:17px;font-weight:700;color:{BRAND_NAVY};line-height:1.3;">'
            f"{_esc(model_name)}</div>"
        )
    equipment_inner = f"""
{model_block}
{_spec_chips_html(specs)}
{tkp_plain_link_html(tkp_url) if tkp_url else ""}
<div style="height:14px;line-height:14px;font-size:0;">&nbsp;</div>
{navy_panel_html(price_inner)}"""

    contacts = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
  <tr>
    {_contact_cell("ФИО", _text_value_html(client_fio))}
    {_contact_cell("Телефон", _text_value_html(phone, link_prefix="tel:"))}
    {_contact_cell("E-mail", _text_value_html(email_addr, link_prefix="mailto:"))}
  </tr>
</table>"""

    body = row_html(
        f'<div style="font-family:{FONT};font-size:20px;font-weight:700;color:{BRAND_NAVY};">{_esc(headline)}</div>'
        f'<div style="font-family:{FONT};font-size:13px;color:{BRAND_MUTED};margin-top:4px;">{_esc(subheadline)}</div>'
        f'<div style="font-family:{FONT};font-size:11px;color:{BRAND_NAVY_LIGHT};margin-top:6px;">'
        f"{_esc(SOURCE_LABELS[src])} · {_esc(SOURCE_HINTS[src])}</div>"
    )
    body += row_html(panel_html(equipment_inner, bgcolor=BRAND_CARD_BG, border="#E2E8F0"))

    if demo_badge:
        body += row_html(
            panel_html(
                '<div style="text-align:center;font-size:12px;color:#92400E;">'
                "Демо · данные сгенерированы автоматически</div>",
                bgcolor="#FFFBEB",
                border="#FDE68A",
            )
        )

    if accessories_lines is not None:
        if accessories_lines:
            lines = "".join(
                f'<div style="padding:5px 0;font-size:13px;color:#2D3748;border-bottom:1px solid #EEF2F6;">'
                f'<span style="color:{BRAND_ORANGE};font-weight:700;">+</span> {_esc(line)}</div>'
                for line in accessories_lines
            )
        else:
            lines = f'<div style="font-size:13px;color:{BRAND_MUTED};">Не выбраны</div>'
        body += row_html(
            panel_html(
                f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'
                f'color:{BRAND_MUTED};margin-bottom:8px;">Комплектующие</div>{lines}'
            )
        )

    if action_hint:
        body += row_html(
            navy_panel_html(
                f'<div style="font-size:13px;font-weight:600;line-height:1.45;">{_esc(action_hint)}</div>'
            )
        )

    body += row_html(contacts)

    return widget_email(
        title=headline,
        badge=badge,
        body_rows=body,
        footer_text=timestamp,
        logo_use_cid=logo_use_cid,
    )


def build_price_inquiry_email_body(
    *,
    equipment_name: str,
    price: str,
    phone: str,
    email: str,
    client_fio: str = "",
    source: str,
    demo_badge: bool = False,
) -> Tuple[str, str, bool]:
    plain = f"""Пользователь узнал цену на расходомер
{_source_block(source)}
═══════════════════════════════════════
ИНФОРМАЦИЯ О РАСХОДОМЕРЕ
═══════════════════════════════════════
{equipment_name}

Предварительная стоимость: {price}

═══════════════════════════════════════
КОНТАКТНЫЕ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ
═══════════════════════════════════════
{_contact_row_plain("ФИО", client_fio)}
{_contact_row_plain("Телефон", phone)}
{_contact_row_plain("E-mail", email)}

═══════════════════════════════════════

Дата и время запроса: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}

---
Автоматическое уведомление из системы подбора оборудования Turbo Flow
"""
    logo_ok = _load_logo_bytes() is not None
    html_body = _build_html_email(
        headline="Новый запрос цены",
        subheadline="Клиент узнал предварительную стоимость на сайте",
        source=source,
        equipment_name=equipment_name,
        price=price,
        phone=phone,
        email_addr=email,
        client_fio=client_fio,
        demo_badge=demo_badge,
        logo_use_cid=logo_ok,
    )
    return plain, html_body, logo_ok


def build_tkp_request_email_body(
    *,
    equipment_name: str,
    price: str,
    phone: str,
    email: str,
    client_fio: str = "",
    accessories: Iterable[Any],
    source: str,
    demo_badge: bool = False,
    tkp_url: Optional[str] = None,
) -> Tuple[str, str, bool]:
    acc_lines = format_accessories_for_email(accessories)
    if acc_lines:
        accessories_text = f"""
═══════════════════════════════════════
ДОПОЛНИТЕЛЬНЫЕ КОМПЛЕКТУЮЩИЕ
═══════════════════════════════════════
{chr(10).join('• ' + line for line in acc_lines)}
"""
    else:
        accessories_text = """
═══════════════════════════════════════
ДОПОЛНИТЕЛЬНЫЕ КОМПЛЕКТУЮЩИЕ
═══════════════════════════════════════
Не выбраны
"""

    plain = f"""Пользователь запросил технико-коммерческое предложение (ТКП)
{_source_block(source)}
═══════════════════════════════════════
ИНФОРМАЦИЯ О РАСХОДОМЕРЕ
═══════════════════════════════════════
{equipment_name}

Предварительная стоимость: {price}
{accessories_text}
═══════════════════════════════════════
КОНТАКТНЫЕ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ
═══════════════════════════════════════
{_contact_row_plain("ФИО", client_fio)}
{_contact_row_plain("Телефон", phone)}
{_contact_row_plain("E-mail", email)}

═══════════════════════════════════════

Дата и время запроса: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
{f"Ссылка на ТКП: {tkp_url}" if tkp_url else ""}

Необходимо подготовить и отправить ТКП на указанный e-mail.

---
Автоматическое уведомление из системы подбора оборудования Turbo Flow
"""
    logo_ok = _load_logo_bytes() is not None
    html_body = _build_html_email(
        headline="Запрос ТКП",
        subheadline="Клиент запросил технико-коммерческое предложение",
        source=source,
        equipment_name=equipment_name,
        price=price,
        phone=phone,
        email_addr=email,
        client_fio=client_fio,
        accessories_lines=acc_lines,
        action_hint="Подготовьте и отправьте ТКП на e-mail клиента",
        tkp_url=tkp_url,
        demo_badge=demo_badge,
        logo_use_cid=logo_ok,
    )
    return plain, html_body, logo_ok


def send_manager_email(
    subject: str,
    plain_body: str,
    html_body: Optional[str] = None,
    *,
    to_email: Optional[str] = None,
    embed_logo: bool = True,
    pdf_attachment: Optional[Tuple[str, bytes]] = None,
) -> Tuple[bool, Optional[str]]:
    recipient = to_email or MANAGER_EMAIL
    if not html_body:
        return False, None
    attachments = [pdf_attachment] if pdf_attachment else None
    ok, err = send_branded_email(
        to_email=recipient,
        subject=subject,
        plain_body=plain_body,
        html_body=html_body,
        embed_logo=embed_logo,
        attachments=attachments,
    )
    if ok:
        logger.info("✅ Письмо менеджеру отправлено на %s: %s", recipient, subject)
    else:
        logger.error("❌ Ошибка отправки письма менеджеру: %s", err)
    return ok, err


def notify_manager_price_inquiry(
    *,
    equipment_name: str,
    price: str,
    phone: str = "",
    email: str = "",
    client_fio: str = "",
    client_name: str = "",
    source: str = SOURCE_SELECTION_MASTER,
) -> Tuple[bool, Optional[str]]:
    fio = normalize_client_fio(client_fio or client_name)
    plain, html_body, _ = build_price_inquiry_email_body(
        equipment_name=equipment_name,
        price=price,
        phone=phone,
        email=email,
        client_fio=fio,
        source=source,
    )
    return send_manager_email(f"Запрос цены: {equipment_name}", plain, html_body)


def notify_manager_tkp_request(
    *,
    equipment_name: str,
    price: str,
    phone: str = "",
    email: str = "",
    client_fio: str = "",
    client_name: str = "",
    accessories: Iterable[Any] = (),
    source: str = SOURCE_SELECTION_MASTER,
    tkp_url: Optional[str] = None,
    tkp_pdf_bytes: Optional[bytes] = None,
) -> Tuple[bool, Optional[str]]:
    fio = normalize_client_fio(client_fio or client_name)
    plain, html_body, _ = build_tkp_request_email_body(
        equipment_name=equipment_name,
        price=price,
        phone=phone,
        email=email,
        client_fio=fio,
        accessories=accessories,
        source=source,
        tkp_url=tkp_url,
    )
    pdf_name = "TKP.pdf"
    if equipment_name:
        safe = re.sub(r"[^\w\-]+", "_", equipment_name.split("(")[0].strip())[:40]
        if safe:
            pdf_name = f"TKP_{safe}.pdf"
    pdf_att = (pdf_name, tkp_pdf_bytes) if tkp_pdf_bytes else None
    if tkp_pdf_bytes:
        plain += "\nPDF ТКП пользователя — во вложении к письму.\n"
    return send_manager_email(
        f"Запрос ТКП: {equipment_name}",
        plain,
        html_body,
        pdf_attachment=pdf_att,
    )


def send_demo_manager_email(to_email: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    plain, html_body, _ = build_price_inquiry_email_body(
        equipment_name="UFG-F-V (DN100, 2 луча, 6.3 МПа, 1–2%)",
        price="3 243 345 ₽",
        phone="79281234567",
        email="client@example.ru",
        client_fio="Иванов Иван Иванович",
        source=SOURCE_SELECTION_MASTER,
        demo_badge=True,
    )
    return send_manager_email(
        "[ДЕМО] Запрос цены: UFG-F-V",
        plain,
        html_body,
        to_email=to_email or MANAGER_EMAIL,
    )


def send_demo_tkp_email(to_email: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    from tkp_pdf import TkpPdfRequest, build_tkp_pdf_bytes
    from tkp_store import save_tkp_pdf
    from email_templates import SITE_URL

    demo_body = TkpPdfRequest(
        equipment_name="UFG-F-V (DN100, 2 луча, 6.3 МПа, 1–2%)",
        price="3 243 345 ₽",
        phone="79281234567",
        email="client@example.ru",
        fio="Иванов Иван Иванович",
        accessories=[
            {"name": "КМЧ", "price": 12500},
            {"name": "Кабель связи", "price": 8400},
        ],
    )
    tkp_url = None
    pdf_bytes: Optional[bytes] = None
    try:
        pdf_bytes = build_tkp_pdf_bytes(demo_body)
        token = save_tkp_pdf(pdf_bytes)
        tkp_url = f"{SITE_URL}/api/tkp-file/{token}"
    except Exception as exc:
        logger.warning("Демо ТКП PDF: %s", exc)

    plain, html_body, _ = build_tkp_request_email_body(
        equipment_name=demo_body.equipment_name,
        price="3 243 345 ₽",
        phone=demo_body.phone or "",
        email=demo_body.email or "",
        client_fio=demo_body.fio or "",
        accessories=["КМЧ (12 500 ₽)", "Кабель связи (8 400 ₽)"],
        source=SOURCE_SELECTION_MASTER,
        tkp_url=tkp_url,
        demo_badge=True,
    )
    if tkp_url:
        plain += f"\nСсылка на ТКП: {tkp_url}\n"
    if pdf_bytes:
        plain += "\nPDF ТКП также во вложении к письму.\n"

    return send_manager_email(
        "[ДЕМО] Запрос ТКП: UFG-F-V",
        plain,
        html_body,
        to_email=to_email or MANAGER_EMAIL,
        pdf_attachment=("TKP_demo_UFG-F-V.pdf", pdf_bytes) if pdf_bytes else None,
    )


if __name__ == "__main__":
    ok, err = send_demo_tkp_email()
    print("OK" if ok else f"FAIL: {err}")

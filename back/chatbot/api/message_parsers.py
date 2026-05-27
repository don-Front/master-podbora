"""Парсеры полей POST /api/chats/<id>/messages/."""

import json

from .order_specs_helpers import safe_print_order_specs_final


def _parse_equipment_for_price(data):
    """Достаёт объект прибора из JSON-тела или FormData (поле equipment_for_price)."""
    eq_raw = data.get('equipment_for_price')
    if eq_raw is None:
        return None
    if isinstance(eq_raw, dict):
        return eq_raw
    if isinstance(eq_raw, str):
        s = eq_raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def _parse_order_specs_for_price(data):
    """Снимок спецификации из PDF (для расчёта цены), из JSON или FormData."""
    raw = data.get('order_specs_for_price')
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None
    return None


def _parse_liquid_installation_lead(data):
    """ФИО и контакт из сценария «поверочные установки — жидкость» (JSON в теле или FormData)."""
    raw = data.get('liquid_installation_lead')
    if raw is None:
        return {}
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    if not isinstance(d, dict):
        return {}
    return {
        'full_name': (d.get('full_name') or '').strip(),
        'email': (d.get('email') or '').strip().lower(),
        'phone': (d.get('phone') or '').strip(),
        'tz_attachment_url': (d.get('tz_attachment_url') or '').strip(),
        'tz_file_name': (d.get('tz_file_name') or '').strip(),
        'tz_comments': (d.get('tz_comments') or '').strip(),
    }


def _normalize_household_selected_items(raw_items):
    """Список выбранных бытовых счётчиков: name, price, quantity."""
    if not isinstance(raw_items, list):
        return []
    out = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = (item.get('name') or '').strip()
        if not name:
            continue
        try:
            price = int(item.get('price') or 0)
        except (TypeError, ValueError):
            price = 0
        try:
            quantity = int(item.get('quantity') or 0)
        except (TypeError, ValueError):
            quantity = 0
        if quantity <= 0:
            continue
        out.append({'name': name, 'price': price, 'quantity': quantity})
    return out


def _parse_household_gas_lead(data):
    """Анкета сценария «бытовые счётчики газа» (JSON в теле или FormData)."""
    raw = data.get('household_gas_lead')
    if raw is None:
        return {}
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    if not isinstance(d, dict):
        return {}
    return {
        'full_name': (d.get('full_name') or '').strip(),
        'email': (d.get('email') or '').strip().lower(),
        'phone': (d.get('phone') or '').strip(),
        'organization': (d.get('organization') or '').strip(),
        'comment': (d.get('comment') or '').strip(),
        'selected_items': _normalize_household_selected_items(d.get('selected_items')),
    }


def _parse_gas_spu_application_lead(data):
    """Анкета «СПУ газ — оставить заявку» (те же поля, что жидкость: ФИО, контакт, ТЗ)."""
    raw = data.get('gas_spu_application_lead')
    if raw is None:
        return {}
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    if not isinstance(d, dict):
        return {}
    return {
        'full_name': (d.get('full_name') or '').strip(),
        'email': (d.get('email') or '').strip().lower(),
        'phone': (d.get('phone') or '').strip(),
        'tz_attachment_url': (d.get('tz_attachment_url') or '').strip(),
        'tz_file_name': (d.get('tz_file_name') or '').strip(),
        'tz_comments': (d.get('tz_comments') or '').strip(),
    }


def _parse_gas_spu(data):
    """Состояние пошагового подбора СПУ (газ), JSON в теле или FormData."""
    raw = data.get('gas_spu_selection')
    if raw is None:
        return {}
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    if not isinstance(d, dict):
        return {}
    return d


def _parse_order_specs_edit_field(data) -> str | None:
    """Поле SPEC_KEYS для редактирования из шага подтверждения."""
    from .pdf_order_analysis import SPEC_KEYS

    raw = data.get("order_specs_edit_field")
    if raw is None or raw == "":
        return None
    key = str(raw).strip()
    return key if key in SPEC_KEYS else None


def _transition_to_order_specs_confirm(chat, draft, *, print_final: bool = True) -> dict:
    """Сохранить черновик, показать сводку; запрос в 1С — только после подтверждения."""
    from .services.order_specs_service import order_specs_service

    return order_specs_service.transition_to_confirm(chat, draft, print_final=print_final)


def _handle_order_specs_text_message(chat_id, text: str, *, base_draft=None) -> dict | None:
    """Свободный текст пользователя -> черновик спецификации -> уточнение или таблица проверки."""
    from .services.order_specs_service import order_specs_service

    return order_specs_service.handle_text_message(chat_id, text, base_draft=base_draft)


def _safe_print_order_specs_final(draft) -> None:
    """Вывод итогового JSON в консоль; не должен ронять запрос при нестандартных типах."""
    safe_print_order_specs_final(draft)


ORDER_SPECS_ATTACHMENT_EXTENSIONS = ('.pdf', '.docx')
ORDER_SPECS_ATTACHMENT_MIME_TYPES = frozenset(
    {
        'application/pdf',
        'application/x-pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }
)


def _is_order_specs_attachment_upload(file_obj):
    """PDF или DOCX для сценария «Расходомеры» (order_pdf_request)."""
    if not file_obj:
        return False
    name = (getattr(file_obj, 'name', '') or '').lower()
    if any(name.endswith(ext) for ext in ORDER_SPECS_ATTACHMENT_EXTENSIONS):
        return True
    ctype = (getattr(file_obj, 'content_type', '') or '').lower().split(';')[0].strip()
    return ctype in ORDER_SPECS_ATTACHMENT_MIME_TYPES


def _is_pdf_upload(file_obj):
    """Обратная совместимость: только PDF."""
    if not file_obj:
        return False
    name = (getattr(file_obj, 'name', '') or '').lower()
    ctype = (getattr(file_obj, 'content_type', '') or '').lower()
    return name.endswith('.pdf') or ctype in ('application/pdf', 'application/x-pdf')


# ТЗ в сценарии «поверочные установки — жидкость»
LIQUID_TZ_MAX_BYTES = 10 * 1024 * 1024
LIQUID_TZ_EXTENSIONS = ('.pdf', '.doc', '.docx', '.txt', '.zip', '.rar')
LIQUID_TZ_MIME_TYPES = frozenset(
    {
        'application/pdf',
        'application/x-pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'application/zip',
        'application/x-zip-compressed',
        'application/x-rar-compressed',
        'application/vnd.rar',
    }
)


def _is_liquid_tz_upload(file_obj):
    """Допустимое вложение ТЗ: расширение или известный MIME (без расширения)."""
    if not file_obj:
        return False
    name = (getattr(file_obj, 'name', '') or '').lower()
    if any(name.endswith(ext) for ext in LIQUID_TZ_EXTENSIONS):
        return True
    ctype = (getattr(file_obj, 'content_type', '') or '').lower().split(';')[0].strip()
    return ctype in LIQUID_TZ_MIME_TYPES

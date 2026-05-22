# -*- coding: utf-8 -*-
"""Навигация «Назад» в сценарии расходомеров (по одному шагу)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .order_specs_helpers import (
    build_order_specs_preview,
    format_prompt_for_field,
    is_value_missing,
    list_missing_fields,
    merge_draft,
    specs_for_api_response,
)
from .pdf_order_analysis import SPEC_KEYS

FLOWMETER_HINT_STATES = frozenset(
    {
        "order_pdf_request",
        "order_specs_clarify",
        "order_specs_confirm",
        "order_final",
        "equipment_price_phone",
        "equipment_price_email",
        "equipment_price_verify_code",
    }
)


def _draft_for_back(chat: Any = None, specs_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Черновик спецификации для шага «Назад» (БД или снимок с фронта)."""
    if chat and chat.order_specs_draft:
        return merge_draft(chat.order_specs_draft)
    if specs_snapshot:
        return merge_draft(specs_snapshot)
    return merge_draft({})


def resolve_flowmeter_back(
    current_state: str,
    chat: Any = None,
    specs_snapshot: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """
    Предыдущий шаг сценария «Расходомеры».

    Returns:
        (next_state, bot_message_override, extras) — extras: order_specs_json, order_specs_preview.
    """
    extras: Dict[str, Any] = {}

    if current_state == "equipment_price_verify_code":
        return "equipment_price_email", None, extras
    if current_state == "equipment_price_email":
        return "equipment_price_phone", None, extras
    if current_state == "equipment_price_phone":
        return "order_final", None, extras

    if current_state == "order_final":
        draft = _draft_for_back(chat, specs_snapshot)
        extras["order_specs_json"] = specs_for_api_response(draft)
        extras["order_specs_preview"] = build_order_specs_preview(draft)
        if chat and not chat.order_specs_draft and any(
            not is_value_missing(k, draft.get(k)) for k in SPEC_KEYS
        ):
            chat.order_specs_draft = draft
            chat.save(update_fields=["order_specs_draft"])
        return "order_specs_confirm", None, extras

    if current_state == "order_specs_confirm":
        draft = _draft_for_back(chat, specs_snapshot)
        if chat and chat.order_specs_pending_field:
            chat.order_specs_pending_field = None
            chat.save(update_fields=["order_specs_pending_field"])
            extras["order_specs_json"] = specs_for_api_response(draft)
            extras["order_specs_preview"] = build_order_specs_preview(draft)
            return "order_specs_confirm", None, extras
        missing = list_missing_fields(draft)
        if missing:
            if chat:
                chat.order_specs_pending_field = missing[-1]
                chat.order_specs_draft = draft
                chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
            extras["order_specs_json"] = specs_for_api_response(draft)
            return (
                "order_specs_clarify",
                format_prompt_for_field(missing[-1]),
                extras,
            )
        return "order_pdf_request", None, extras

    if current_state == "order_specs_clarify" and chat:
        draft = merge_draft(chat.order_specs_draft or {})
        pending = chat.order_specs_pending_field
        missing = list_missing_fields(draft)

        if pending and not is_value_missing(pending, draft.get(pending)):
            chat.order_specs_pending_field = None
            chat.order_specs_draft = draft
            chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
            extras["order_specs_json"] = specs_for_api_response(draft)
            extras["order_specs_preview"] = build_order_specs_preview(draft)
            return "order_specs_confirm", None, extras

        if pending and pending in SPEC_KEYS:
            idx = SPEC_KEYS.index(pending)
            prior_missing = [k for k in SPEC_KEYS if k in missing and SPEC_KEYS.index(k) < idx]
            if prior_missing:
                prev_key = prior_missing[-1]
                draft[prev_key] = None
                chat.order_specs_draft = draft
                chat.order_specs_pending_field = prev_key
                chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
                extras["order_specs_json"] = specs_for_api_response(draft)
                return "order_specs_clarify", format_prompt_for_field(prev_key), extras

        if chat.order_specs_draft:
            extras["order_specs_json"] = specs_for_api_response(draft)
            extras["order_specs_preview"] = build_order_specs_preview(draft)
            chat.order_specs_pending_field = None
            chat.save(update_fields=["order_specs_pending_field"])
            return "order_specs_confirm", None, extras

        return "order_pdf_request", None, extras

    if current_state == "order_pdf_request":
        return "equipment_pick", None, extras

    return "equipment_pick", None, extras

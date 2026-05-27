"""Обработка сценария спецификации заказа (order_specs_*)."""

from __future__ import annotations

import logging
import os

from django.conf import settings

from ..hints_tree import get_state
from ..message_parsers import (
    _handle_order_specs_text_message,
    _is_order_specs_attachment_upload,
    _transition_to_order_specs_confirm,
)
from ..models import Chat
from ..order_specs_helpers import (
    ORDER_SPECS_CONFIRM_HINT,
    build_order_specs_preview,
    format_prompt_for_field,
    list_missing_fields,
    merge_draft,
    parse_field_value,
    specs_for_api_response,
)
from .message_flow_context import MessageFlowContext

logger = logging.getLogger(__name__)

_ORDER_SPECS_STATES = frozenset(
    {
        'order_pdf_request',
        'order_specs_text_clarify',
        'order_specs_clarify',
        'order_specs_confirm',
    }
)


class OrderSpecsFlowHandler:
    @staticmethod
    def handles(state: str) -> bool:
        return state in _ORDER_SPECS_STATES

    @staticmethod
    def handle(ctx: MessageFlowContext) -> None:
        state = ctx.current_state
        chat_id = ctx.chat_id
        question = ctx.question
        attachment_file = ctx.attachment_file
        image_file = ctx.image_file
        user_message = ctx.user_message
        state_data = ctx.state_data
        order_specs_edit_field = ctx.order_specs_edit_field

        if state == 'order_pdf_request':
            has_specs_doc = _is_order_specs_attachment_upload(attachment_file)
            has_image = bool(image_file)
            text = (question or '').strip()
            if has_specs_doc:
                abs_pdf = os.path.join(settings.MEDIA_ROOT, str(user_message.attachment))
                thanks_template = get_state("order_final").get("bot_message") or ""
                try:
                    logger.info(
                        "[Чатбот заказ] Принят файл спецификации (chat_id=%s); OCR/DOCX -> LM Studio",
                        chat_id,
                    )
                    from ..services.order_specs_service import order_specs_service

                    specs, _ocr_text, pipeline_err, llm_raw, pdf_timing = (
                        order_specs_service.extract_from_pdf(abs_pdf)
                    )
                    ctx.order_specs_pipeline_timing = pdf_timing
                    logger.info(
                        "[Чатбот PDF] Пайплайн завершён (chat_id=%s); предупреждение/ошибка: %s",
                        chat_id,
                        pipeline_err or "нет",
                    )
                    ctx.order_specs_llm_response = llm_raw
                    ctx.order_specs_ocr_text = _ocr_text
                    draft = merge_draft(specs)
                    ctx.order_specs_json = draft

                    chat = Chat.objects.get(pk=chat_id)
                    chat.order_specs_draft = draft
                    missing = list_missing_fields(draft)

                    if missing:
                        chat.order_specs_pending_field = missing[0]
                        chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
                        ctx.next_state = "order_specs_clarify"
                        intro = ""
                        if pipeline_err:
                            intro = (
                                f"Часть данных из файла распознана не полностью ({pipeline_err}).\n\n"
                            )
                        ctx.bot_response = intro + format_prompt_for_field(missing[0])
                        ctx.hint_locked = True
                    else:
                        trans = _transition_to_order_specs_confirm(chat, draft)
                        ctx.next_state = trans["next_state"]
                        ctx.bot_response = trans["bot_response"]
                        ctx.order_specs_json = trans["order_specs_json"]
                        ctx.order_specs_preview = trans.get("order_specs_preview")
                        ctx.hint_locked = True
                except Exception as e:
                    logger.exception("[Чатбот PDF] Ошибка пайлайна: %s", e)
                    print(f"[ERROR] pdf_order_pipeline: {e}")
                    ctx.order_specs_json = None
                    ctx.next_state = state_data.get("next_state", "order_final")
                    ctx.bot_response = (
                        f"Не удалось обработать файл автоматически: {e}\n\n{thanks_template}"
                    )
                    ctx.hint_locked = True
            elif has_image:
                ctx.bot_response = (
                    "Нужен документ PDF или DOCX с характеристиками оборудования. "
                    "Пожалуйста, прикрепите файл, а не изображение."
                )
                ctx.next_state = state
            elif text:
                ctx.bot_response = (
                    "Для оформления заказа пришлите, пожалуйста, файл PDF или DOCX с описанием "
                    "характеристик оборудования (кнопка скрепки 📎)."
                )
                ctx.next_state = state
            else:
                ctx.bot_response = (
                    "Пожалуйста, прикрепите и отправьте файл PDF или DOCX с описанием "
                    "характеристик оборудования."
                )
                ctx.next_state = state

        elif state == 'order_specs_text_clarify':
            text = (question or "").strip()
            chat = Chat.objects.filter(pk=chat_id).first()
            if not chat:
                ctx.bot_response = "Сессия чата устарела. Начните диалог заново."
                ctx.next_state = "start"
                ctx.hint_locked = False
            elif not text:
                from ..order_specs_text import (
                    build_order_specs_clarify_preview,
                    format_text_specs_clarification,
                )

                draft = merge_draft(chat.order_specs_draft or {})
                missing = list_missing_fields(draft)
                ctx.bot_response = format_text_specs_clarification(draft, missing)
                ctx.order_specs_clarify_preview = build_order_specs_clarify_preview(draft, missing)
                ctx.next_state = "order_specs_text_clarify"
                ctx.order_specs_json = draft
                ctx.hint_locked = True
            else:
                specs_text_result = _handle_order_specs_text_message(
                    chat_id,
                    text,
                    base_draft=chat.order_specs_draft or {},
                )
                ctx.next_state = specs_text_result["next_state"]
                ctx.bot_response = specs_text_result["bot_response"]
                ctx.order_specs_json = specs_text_result.get("order_specs_json")
                ctx.order_specs_preview = specs_text_result.get("order_specs_preview")
                ctx.order_specs_clarify_preview = specs_text_result.get("order_specs_clarify_preview")
                ctx.order_specs_llm_response = specs_text_result.get("order_specs_llm_response")
                ctx.hint_locked = specs_text_result["hint_locked"]

        elif state == 'order_specs_clarify':
            text = (question or "").strip()
            chat = Chat.objects.filter(pk=chat_id).first()
            if not chat:
                ctx.bot_response = "Сессия чата устарела. Начните диалог заново."
                ctx.next_state = "start"
                ctx.hint_locked = False
            else:
                draft = merge_draft(chat.order_specs_draft or {})
                pending = chat.order_specs_pending_field
                missing_pre = list_missing_fields(draft)
                if not pending and missing_pre:
                    pending = missing_pre[0]
                    chat.order_specs_pending_field = pending
                    chat.save(update_fields=["order_specs_pending_field"])

                if not text:
                    if pending or missing_pre:
                        key = pending or (missing_pre[0] if missing_pre else None)
                        if key:
                            ctx.bot_response = format_prompt_for_field(key)
                        else:
                            ctx.bot_response = "Введите значение в поле ниже и отправьте."
                    else:
                        ctx.bot_response = "Введите значение текстом."
                    ctx.next_state = "order_specs_clarify"
                    ctx.order_specs_json = draft
                    ctx.hint_locked = True
                else:
                    key = pending or (missing_pre[0] if missing_pre else None)
                    if not key:
                        trans = _transition_to_order_specs_confirm(chat, draft)
                        ctx.next_state = trans["next_state"]
                        ctx.bot_response = trans["bot_response"]
                        ctx.order_specs_json = trans["order_specs_json"]
                        ctx.order_specs_preview = trans.get("order_specs_preview")
                        ctx.hint_locked = True
                    else:
                        try:
                            draft[key] = parse_field_value(key, text)
                        except ValueError as ve:
                            ctx.bot_response = (
                                f"Не удалось разобрать ответ ({ve}). "
                                f"Повторите ввод.\n\n{format_prompt_for_field(key)}"
                            )
                            ctx.next_state = "order_specs_clarify"
                            ctx.order_specs_json = draft
                            ctx.hint_locked = True
                        else:
                            chat.order_specs_draft = draft
                            missing = list_missing_fields(draft)
                            if missing:
                                chat.order_specs_pending_field = missing[0]
                                chat.save(
                                    update_fields=[
                                        "order_specs_draft",
                                        "order_specs_pending_field",
                                    ]
                                )
                                ctx.bot_response = format_prompt_for_field(missing[0])
                                ctx.next_state = "order_specs_clarify"
                                ctx.order_specs_json = draft
                                ctx.hint_locked = True
                            else:
                                trans = _transition_to_order_specs_confirm(chat, draft)
                                ctx.next_state = trans["next_state"]
                                ctx.bot_response = trans["bot_response"]
                                ctx.order_specs_json = trans["order_specs_json"]
                                ctx.order_specs_preview = trans.get("order_specs_preview")
                                ctx.hint_locked = True

        elif state == 'order_specs_confirm':
            if order_specs_edit_field:
                chat = Chat.objects.filter(pk=chat_id).first()
                if not chat:
                    ctx.bot_response = "Сессия чата устарела. Начните диалог заново."
                    ctx.next_state = "start"
                    ctx.hint_locked = False
                else:
                    draft = merge_draft(chat.order_specs_draft or {})
                    chat.order_specs_pending_field = order_specs_edit_field
                    chat.save(update_fields=["order_specs_pending_field"])
                    ctx.next_state = "order_specs_clarify"
                    ctx.bot_response = format_prompt_for_field(order_specs_edit_field)
                    ctx.order_specs_json = specs_for_api_response(draft)
                    ctx.hint_locked = True
            else:
                ctx.next_state = state
                ctx.bot_response = (
                    f"Для продолжения нажмите «{ORDER_SPECS_CONFIRM_HINT}» под таблицей параметров."
                )
                chat = Chat.objects.filter(pk=chat_id).first()
                if chat and chat.order_specs_draft:
                    ctx.order_specs_preview = build_order_specs_preview(
                        merge_draft(chat.order_specs_draft)
                    )
                ctx.hint_locked = True

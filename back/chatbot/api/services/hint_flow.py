"""Обработка выбора подсказки (is_hint_selection)."""

from __future__ import annotations

from ..hints_tree import get_next_state, get_state
from ..message_parsers import (
    _parse_gas_spu,
    _parse_household_gas_lead,
    _parse_liquid_installation_lead,
    _safe_print_order_specs_final,
)
from ..models import Chat
from ..order_specs_helpers import (
    ORDER_SPECS_CONFIRM_HINT,
    build_order_specs_preview,
    format_prompt_for_field,
    list_missing_fields,
    merge_draft,
    specs_for_api_response,
)
from .message_flow_context import MessageFlowContext
from .price_flow import PriceFlowHandler


class HintFlowHandler:
    @staticmethod
    def handle(ctx: MessageFlowContext) -> None:
        q_sel = (ctx.question or '').strip()
        data = ctx.request_data
        current_state = ctx.current_state
        chat_id = ctx.chat_id
        order_specs_edit_field = ctx.order_specs_edit_field

        if q_sel == 'Получить цену' and current_state == 'order_final':
            PriceFlowHandler.handle_price_hint(ctx)
        elif current_state == 'verification_installations_gas':
            from ..gas_spu_wizard import GAS_SPU_LEAVE_REQUEST
            from ..gas_spu_wizard import apply_hint as gas_apply_hint

            gctx = _parse_gas_spu(data)
            sel_txt = (ctx.question or '').strip()
            wants_gas_spu_application = sel_txt.casefold().startswith('оставить заявку')
            if (
                ctx.is_hint_selection
                and (sel_txt == GAS_SPU_LEAVE_REQUEST or wants_gas_spu_application)
                and gctx.get('step') == 'gas_done'
            ):
                ctx.next_state = 'verification_installations_gas_application'
                next_state_data = get_state(ctx.next_state)
                ctx.bot_response = next_state_data.get('bot_message') or ''
                ctx.gas_spu_selection = gctx
                ctx.gas_spu_application_lead = {
                    'full_name': '',
                    'email': '',
                    'phone': '',
                    'tz_attachment_url': '',
                    'tz_file_name': '',
                    'tz_comments': '',
                }
                ctx.hint_locked = True
            else:
                ctx.next_state = 'verification_installations_gas'
                ctx.hint_locked = True
                gr = gas_apply_hint(gctx, sel_txt if ctx.is_hint_selection else None)
                ctx.gas_spu_selection = gr.ctx
                ctx.bot_response = gr.message
                ctx.gas_hints = gr.hints
                ctx.gas_expects = gr.expects_input
                ctx.gas_spu_card = gr.card
                ctx.gas_spu_preview = gr.preview
        elif current_state == 'equipment_household_gas_dev':
            lead_ctx = _parse_household_gas_lead(data)
            selected_items = lead_ctx.get('selected_items') or []
            if not selected_items:
                ctx.bot_response = 'Выберите хотя бы одну позицию в прайс-листе перед оформлением заявки.'
                ctx.next_state = current_state
                ctx.hint_locked = True
                ctx.household_gas_lead = {
                    'full_name': '',
                    'email': '',
                    'phone': '',
                    'organization': '',
                    'comment': '',
                    'selected_items': [],
                }
            else:
                ctx.household_gas_lead = {
                    'full_name': '',
                    'email': '',
                    'phone': '',
                    'organization': '',
                    'comment': '',
                    'selected_items': selected_items,
                }
                ctx.next_state = 'household_gas_fullname'
                next_state_data = get_state(ctx.next_state)
                ctx.bot_response = next_state_data.get('bot_message') or ''
                ctx.hint_locked = True
        elif current_state == 'order_specs_confirm':
            if order_specs_edit_field:
                try:
                    ch = Chat.objects.get(pk=chat_id)
                    draft = merge_draft(ch.order_specs_draft or {})
                    ch.order_specs_pending_field = order_specs_edit_field
                    ch.save(update_fields=["order_specs_pending_field"])
                    ctx.next_state = "order_specs_clarify"
                    ctx.bot_response = format_prompt_for_field(order_specs_edit_field)
                    ctx.order_specs_json = specs_for_api_response(draft)
                    ctx.hint_locked = True
                except Chat.DoesNotExist:
                    ctx.bot_response = "Сессия чата устарела. Начните диалог заново."
                    ctx.next_state = "start"
                    ctx.hint_locked = False
            elif ctx.is_hint_selection and (ctx.question or '').strip() == ORDER_SPECS_CONFIRM_HINT:
                try:
                    ch = Chat.objects.get(pk=chat_id)
                    draft = merge_draft(ch.order_specs_draft or {})
                    missing = list_missing_fields(draft)
                    if missing:
                        ch.order_specs_pending_field = missing[0]
                        ch.order_specs_draft = draft
                        ch.save(
                            update_fields=["order_specs_draft", "order_specs_pending_field"]
                        )
                        ctx.next_state = "order_specs_clarify"
                        ctx.bot_response = format_prompt_for_field(missing[0])
                        ctx.order_specs_json = specs_for_api_response(draft)
                        ctx.hint_locked = True
                    else:
                        _safe_print_order_specs_final(draft)
                        ch.order_specs_draft = draft
                        ch.order_specs_pending_field = None
                        ch.save(
                            update_fields=["order_specs_draft", "order_specs_pending_field"]
                        )
                        ctx.next_state = "order_final"
                        ctx.order_specs_json = specs_for_api_response(draft)
                        ctx.bot_response = ""
                        ctx.allow_empty_bot = True
                        ctx.hint_locked = True
                except Chat.DoesNotExist:
                    ctx.bot_response = "Сессия чата устарела. Начните диалог заново."
                    ctx.next_state = "start"
                    ctx.hint_locked = False
            else:
                ctx.next_state = current_state
                ctx.bot_response = (
                    f"Нажмите «{ORDER_SPECS_CONFIRM_HINT}», чтобы отправить параметры на подбор."
                )
                try:
                    ch = Chat.objects.get(pk=chat_id)
                    ctx.order_specs_preview = build_order_specs_preview(
                        merge_draft(ch.order_specs_draft or {})
                    )
                except Chat.DoesNotExist:
                    pass
                ctx.hint_locked = True
        else:
            ctx.next_state = get_next_state(current_state, ctx.question)
            next_state_data = get_state(ctx.next_state)
            ctx.bot_response = next_state_data.get('bot_message') or ''
            ctx.hint_locked = True
            if ctx.next_state == 'verification_installations_gas' and current_state == 'verification_installations':
                from ..gas_spu_wizard import entry_after_menu as gas_entry

                gr = gas_entry()
                ctx.gas_spu_selection = gr.ctx
                ctx.bot_response = gr.message
                ctx.gas_hints = gr.hints
                ctx.gas_expects = gr.expects_input
                ctx.gas_spu_preview = gr.preview
                lead_ctx = _parse_liquid_installation_lead(data)
                ctx.liquid_installation_lead = {
                    'full_name': lead_ctx.get('full_name') or '',
                    'email': lead_ctx.get('email') or '',
                    'phone': lead_ctx.get('phone') or '',
                    'tz_attachment_url': '',
                    'tz_file_name': '',
                    'tz_comments': '',
                }
                ctx.bot_response = (
                    'Хорошо, продолжаем без вложения технического задания.\n\n' + ctx.bot_response
                )
            if ctx.next_state == "order_pdf_request":
                try:
                    ch = Chat.objects.get(pk=chat_id)
                    ch.order_specs_draft = None
                    ch.order_specs_pending_field = None
                    ch.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
                except Chat.DoesNotExist:
                    pass

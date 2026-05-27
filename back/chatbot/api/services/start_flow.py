"""Обработка start-like состояний (свободный ввод / order specs text)."""

from __future__ import annotations

from ..message_parsers import _handle_order_specs_text_message
from .message_flow_context import MessageFlowContext


class StartFlowHandler:
    @staticmethod
    def handle(ctx: MessageFlowContext) -> None:
        text = (ctx.question or "").strip()
        from ..services.order_specs_service import order_specs_service

        specs_text_result = None
        if order_specs_service.looks_like_order_specs(text):
            specs_text_result = _handle_order_specs_text_message(
                ctx.chat_id, text, base_draft={}
            )

        if specs_text_result:
            ctx.next_state = specs_text_result["next_state"]
            ctx.bot_response = specs_text_result["bot_response"]
            ctx.order_specs_json = specs_text_result.get("order_specs_json")
            ctx.order_specs_preview = specs_text_result.get("order_specs_preview")
            ctx.order_specs_clarify_preview = specs_text_result.get("order_specs_clarify_preview")
            ctx.order_specs_llm_response = specs_text_result.get("order_specs_llm_response")
            ctx.hint_locked = specs_text_result["hint_locked"]
        else:
            from . import faq_service

            if faq_service.apply_to_context(ctx):
                return

            from ..services.rag_service import rag_service

            ctx.bot_response = rag_service.answer(ctx.question, chat_id=ctx.chat_id)
            ctx.rag_llm_ms = rag_service.last_llm_elapsed_ms
            ctx.hint_locked = False

"""Маршрутизация POST /api/chats/<id>/messages/."""

from __future__ import annotations

from .hint_flow import HintFlowHandler
from .locked_flow import LockedFlowHandler
from .message_flow_context import MessageFlowContext
from .order_specs_flow import OrderSpecsFlowHandler
from .start_flow import StartFlowHandler


class MessageFlowRouter:
    @staticmethod
    def route(ctx: MessageFlowContext) -> None:
        if ctx.is_hint_selection:
            HintFlowHandler.handle(ctx)
        elif OrderSpecsFlowHandler.handles(ctx.current_state):
            # Подбор расходомеров: файл или текст — всегда через order_specs, не RAG
            OrderSpecsFlowHandler.handle(ctx)
        elif ctx.is_start_like:
            StartFlowHandler.handle(ctx)
        elif ctx.hint_locked:
            LockedFlowHandler.handle(ctx)
        else:
            from . import competitor_mask_service, faq_service

            if competitor_mask_service.apply_to_context(ctx):
                return

            if faq_service.apply_to_context(ctx):
                return

            from ..services.rag_service import rag_service

            ctx.bot_response = rag_service.answer(ctx.question, chat_id=ctx.chat_id)
            ctx.rag_llm_ms = rag_service.last_llm_elapsed_ms
            ctx.rag_sources = list(rag_service.last_rag_sources or [])

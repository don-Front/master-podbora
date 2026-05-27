"""Маршрутизация POST /api/chats/<id>/messages/."""

from __future__ import annotations

from .hint_flow import HintFlowHandler
from .locked_flow import LockedFlowHandler
from .message_flow_context import MessageFlowContext
from .start_flow import StartFlowHandler


class MessageFlowRouter:
    @staticmethod
    def route(ctx: MessageFlowContext) -> None:
        from . import faq_service

        if ctx.is_hint_selection and faq_service.apply_to_context(ctx, from_hint=True):
            return

        if ctx.is_hint_selection:
            HintFlowHandler.handle(ctx)
        elif ctx.is_start_like:
            StartFlowHandler.handle(ctx)
        elif ctx.hint_locked:
            LockedFlowHandler.handle(ctx)
        else:
            if faq_service.apply_to_context(ctx):
                return

            from ..services.rag_service import rag_service

            ctx.bot_response = rag_service.answer(ctx.question, chat_id=ctx.chat_id)
            ctx.rag_llm_ms = rag_service.last_llm_elapsed_ms

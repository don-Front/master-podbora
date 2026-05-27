"""Диспетчер locked-состояний (hint_locked)."""

from __future__ import annotations

from ..hints_tree import get_state
from .message_flow_context import MessageFlowContext
from .order_specs_flow import OrderSpecsFlowHandler
from .price_flow import PriceFlowHandler
from .verification_flow import VerificationFlowHandler


class LockedFlowHandler:
    @staticmethod
    def handle(ctx: MessageFlowContext) -> None:
        state = ctx.current_state

        if OrderSpecsFlowHandler.handles(state):
            OrderSpecsFlowHandler.handle(ctx)
        elif state == 'verification_installations_gas':
            VerificationFlowHandler.handle(ctx)
        elif PriceFlowHandler.handles(state):
            PriceFlowHandler.handle(ctx)
        elif VerificationFlowHandler.handles(state):
            VerificationFlowHandler.handle(ctx)
        elif ctx.state_data.get('expects_input', False):
            ctx.next_state = ctx.state_data.get('next_state', state)
            next_state_data = get_state(ctx.next_state)
            ctx.bot_response = next_state_data.get('bot_message') or ''
        else:
            ctx.bot_response = (
                "Пожалуйста, выберите один из предложенных вариантов или нажмите 'Вернуться'."
            )
            ctx.next_state = state

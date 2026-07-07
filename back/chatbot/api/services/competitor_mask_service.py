"""Интеграция расшифровки масок конкурентов в message flow."""

from __future__ import annotations

import logging

from ..competitor_masks import competitor_mask_decoder
from ..competitor_masks.analog_mapper import ANALOG_INTRO, build_analog_search_specs
from ..competitor_masks.card_builder import build_competitor_mask_card
from ..competitor_masks.comparison_builder import build_competitor_comparison_card
from .message_flow_context import MessageFlowContext

logger = logging.getLogger(__name__)


def apply_to_context(ctx: MessageFlowContext) -> bool:
    """
    Если сообщение — маска конкурента, сформировать ответ без RAG/FAQ.

    Returns:
        True, если сценарий обработан.
    """
    text = (ctx.question or "").strip()
    if not text:
        return False
    if not competitor_mask_decoder.looks_like_mask(text):
        return False

    result = competitor_mask_decoder.decode(text)
    if not result.handled:
        return False

    ctx.competitor_mask_card = build_competitor_mask_card(result)
    ctx.competitor_comparison_card = build_competitor_comparison_card(result.catalog_id)
    analog = build_analog_search_specs(
        result.catalog_id,
        result.parsed_fields,
        is_valid=result.is_valid,
    )
    ctx.competitor_analog_specs = analog.specs
    ctx.competitor_analog_intro = analog.intro if analog.specs else None
    ctx.competitor_analog_skip_reason = analog.skip_reason
    ctx.bot_response = ""
    ctx.allow_empty_bot = True
    if analog.specs:
        # Тот же финальный шаг, что после «Подтвердить и подобрать оборудование» в PDF-сценарии.
        ctx.order_specs_json = analog.specs
        ctx.next_state = "order_final"
        ctx.hint_locked = False
    else:
        ctx.next_state = "start"
        ctx.hint_locked = False
    ctx.rag_llm_ms = 0.0
    logger.info("Competitor mask flow handled for chat_id=%s", ctx.chat_id)
    return True

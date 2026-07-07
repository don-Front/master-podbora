"""Контекст обработки POST /api/chats/<id>/messages/."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MessageFlowContext:
    chat_id: int
    request_data: dict
    question: str
    current_state: str
    is_hint_selection: bool
    hint_locked: bool
    state_data: dict
    is_start_like: bool
    image_file: Any = None
    attachment_file: Any = None
    user_message: Any = None
    http_request: Any = None
    order_specs_edit_field: Optional[str] = None

    bot_response: str = ""
    next_state: str = ""
    order_specs_json: Any = None
    order_specs_preview: Any = None
    order_specs_clarify_preview: Any = None
    order_specs_llm_response: Any = None
    order_specs_ocr_text: Any = None
    order_specs_pipeline_timing: Any = None
    rag_llm_ms: float = 0.0
    allow_empty_bot: bool = False
    suppress_chat_email: bool = False
    verification_passed: bool = False
    verified_contact: Any = None
    liquid_installation_lead: Any = None
    submit_verification_liquid_result: Any = None
    gas_spu_application_lead: Any = None
    submit_spu_application_result: Any = None
    household_gas_lead: Any = None
    submit_household_gas_result: Any = None
    gas_spu_selection: Any = None
    gas_spu_card: Any = None
    gas_spu_preview: Any = None
    gas_hints: Any = field(default=None, repr=False)
    gas_expects: Any = field(default=None, repr=False)
    bot_attachment_path: Any = None
    bot_attachment_name: str = ""
    faq_card: Any = None
    competitor_mask_card: Any = None
    competitor_comparison_card: Any = None
    competitor_analog_specs: Any = None
    competitor_analog_intro: str | None = None
    competitor_analog_skip_reason: str | None = None
    rag_sources: Any = field(default_factory=list)

    def apply_result(self, result: Dict[str, Any]) -> None:
        """Применить dict результата от flow-обработчика."""
        for key, value in result.items():
            if key == "_gas_hints":
                self.gas_hints = value
            elif key == "_gas_expects":
                self.gas_expects = value
            elif hasattr(self, key):
                setattr(self, key, value)

    def to_response_extras(self) -> dict:
        return {
            "order_specs_json": self.order_specs_json,
            "order_specs_preview": self.order_specs_preview,
            "order_specs_clarify_preview": self.order_specs_clarify_preview,
            "order_specs_llm_response": self.order_specs_llm_response,
            "order_specs_ocr_text": self.order_specs_ocr_text,
            "order_specs_pipeline_timing": self.order_specs_pipeline_timing,
            "verification_passed": self.verification_passed,
            "verified_contact": self.verified_contact,
            "liquid_installation_lead": self.liquid_installation_lead,
            "submit_verification_liquid": self.submit_verification_liquid_result,
            "gas_spu_application_lead": self.gas_spu_application_lead,
            "submit_spu_application": self.submit_spu_application_result,
            "household_gas_lead": self.household_gas_lead,
            "submit_household_gas": self.submit_household_gas_result,
            "gas_spu_selection": self.gas_spu_selection,
            "gas_spu_card": self.gas_spu_card,
            "gas_spu_preview": self.gas_spu_preview,
            "faq_card": self.faq_card,
            "competitor_mask_card": self.competitor_mask_card,
            "competitor_comparison_card": self.competitor_comparison_card,
            "rag_sources": self.rag_sources or None,
        }

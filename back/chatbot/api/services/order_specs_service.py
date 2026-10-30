"""Сервис подбора оборудования: PDF, свободный текст, черновик спецификации."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import yaml

from ..models import Chat
from ..order_specs_helpers import (
    build_order_specs_preview,
    format_specs_summary_for_user,
    list_missing_fields,
    merge_draft,
    specs_for_api_response,
)
from ..order_specs_text import (
    TEXT_ORDER_SPECS_STATE,
    build_order_specs_clarify_preview,
    extract_order_specs_from_text,
    format_text_specs_clarification,
    looks_like_order_specs_request,
    present_fields,
)
from ..chatbot_core.rag_messages import is_llm_system_error_text
from ..pdf_order_analysis import run_pdf_order_pipeline
from ..search_equipment import build_search_equipment_params

logger = logging.getLogger(__name__)

_LLM_UNAVAILABLE_WARNING = (
    "Автоматическое извлечение через LLM временно недоступно; "
    "часть параметров определена по текстовым правилам."
)


def _resolve_config_path() -> str:
    current_file = os.path.abspath(__file__)
    project_root = os.path.normpath(
        os.path.join(os.path.dirname(current_file), "..", "..", "..", "project")
    )
    config_path = os.path.normpath(os.path.join(project_root, "config.yaml"))
    if os.path.exists(config_path):
        return config_path
    return r"C:\temp\chatbot\config.yaml"


class OrderSpecsService:
    """PDF/DOCX и текстовый подбор параметров расходомера."""

    def __init__(self, llm_client=None) -> None:
        self._llm = llm_client

    @property
    def llm(self):
        """LLM-клиент для извлечения JSON (lazy init, без загрузки RAG)."""
        if self._llm is None:
            from ..chatbot_core.llm_client import LLMClient

            with open(_resolve_config_path(), "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            llm_config = config.get("llm") or {}
            required = ["base_url", "model", "temperature", "max_tokens"]
            missing = [k for k in required if not llm_config.get(k)]
            if missing:
                raise ValueError(
                    f"В config.yaml не заполнены параметры llm: {', '.join(missing)}"
                )
            self._llm = LLMClient(**llm_config)
        return self._llm

    def looks_like_order_specs(self, text: str) -> bool:
        return looks_like_order_specs_request(text)

    def extract_from_pdf(self, file_path: str) -> Tuple[Dict[str, Any], str, str, str, Dict[str, Any]]:
        """
        OCR/DOCX → LLM → JSON спецификации.

        Returns:
            (specs_dict, ocr_text, error_message, llm_raw, timing)
        """
        return run_pdf_order_pipeline(file_path, self.llm)

    def extract_from_text(
        self,
        message: str,
        existing_draft: Optional[Dict[str, Any]] = None,
        *,
        use_llm: bool = True,
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        """Свободный текст → черновик спецификации."""
        llm = self.llm if use_llm else None
        try:
            return extract_order_specs_from_text(message, llm, existing_draft)
        except Exception:
            if use_llm:
                logger.exception("[OrderSpecsService] LLM недоступен, fallback на эвристики")
                return extract_order_specs_from_text(message, None, existing_draft)
            raise

    def specs_for_search(self, specs: Dict[str, Any]) -> Dict[str, str]:
        """Query-параметры GET /api/search-equipment для :8010."""
        return build_search_equipment_params(specs)

    def transition_to_confirm(self, chat: Chat, draft: Dict[str, Any], *, print_final: bool = True) -> dict:
        """Сохранить черновик и вернуть payload для шага order_specs_confirm."""
        from ..order_specs_helpers import safe_print_order_specs_final

        d = merge_draft(draft)
        if print_final:
            safe_print_order_specs_final(d)
        chat.order_specs_draft = d
        chat.order_specs_pending_field = None
        chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
        return {
            "next_state": "order_specs_confirm",
            "bot_response": format_specs_summary_for_user(d),
            "order_specs_json": specs_for_api_response(d),
            "order_specs_preview": build_order_specs_preview(d),
        }

    def handle_text_message(
        self,
        chat_id: int,
        text: str,
        *,
        base_draft: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """Свободный текст в start → уточнение или таблица подтверждения."""
        chat = Chat.objects.filter(pk=chat_id).first()
        if not chat:
            return {
                "next_state": "start",
                "bot_response": "Сессия чата устарела. Начните диалог заново.",
                "order_specs_json": None,
                "order_specs_preview": None,
                "order_specs_llm_response": None,
                "hint_locked": False,
            }

        base = merge_draft(base_draft or {})
        warning = ""
        try:
            draft, llm_raw, extract_err, _timing = self.extract_from_text(text, base, use_llm=True)
            if extract_err:
                if is_llm_system_error_text(extract_err):
                    logger.warning(
                        "[OrderSpecsService] LLM extract error (masked): %s",
                        extract_err,
                    )
                    warning = _LLM_UNAVAILABLE_WARNING
                else:
                    warning = (
                        "Часть параметров удалось определить правилами, "
                        "но LLM-извлечение вернуло предупреждение."
                    )
        except Exception as exc:
            logger.exception("[OrderSpecsService] ошибка извлечения: %s", exc)
            draft, llm_raw, extract_err, _timing = self.extract_from_text(text, base, use_llm=False)
            warning = _LLM_UNAVAILABLE_WARNING

        draft = merge_draft(draft)
        missing = list_missing_fields(draft)
        chat.order_specs_draft = draft
        chat.order_specs_pending_field = None

        if missing:
            chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
            return {
                "next_state": TEXT_ORDER_SPECS_STATE,
                "bot_response": format_text_specs_clarification(draft, missing, warning=warning),
                "order_specs_json": specs_for_api_response(draft),
                "order_specs_preview": None,
                "order_specs_clarify_preview": build_order_specs_clarify_preview(
                    draft, missing, warning=warning
                ),
                "order_specs_llm_response": llm_raw,
                "hint_locked": True,
            }

        if not present_fields(draft):
            chat.save(update_fields=["order_specs_draft", "order_specs_pending_field"])
            return {
                "next_state": TEXT_ORDER_SPECS_STATE,
                "bot_response": (
                    "Не удалось надёжно определить параметры расходомера из сообщения. "
                    "Напишите, пожалуйста, среду, расход, давление, температуру, точность и DN одним сообщением."
                ),
                "order_specs_json": specs_for_api_response(draft),
                "order_specs_preview": None,
                "order_specs_llm_response": llm_raw,
                "hint_locked": True,
            }

        trans = self.transition_to_confirm(chat, draft)
        trans["order_specs_llm_response"] = llm_raw
        trans["hint_locked"] = True
        return trans


order_specs_service = OrderSpecsService()

"""RAG-сервис: инициализация чатбота, ответы, healthcheck."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from ..chatbot_core import AdvancedChatbot
from ..chatbot_core.product_detector import (
    TROUBLESHOOTING_EQUIPMENT_CLARIFY,
    VERIFICATION_EQUIPMENT_CLARIFY,
    VERIFICATION_EQUIPMENT_NOT_FOUND,
    _is_malfunction_query,
    _is_verification_query,
    inject_verification_equipment,
    looks_like_equipment_clarification_reply,
    looks_like_verification_equipment_reply,
    merge_troubleshooting_followup,
    merge_verification_followup,
    needs_verification_equipment_clarification,
    resolve_catalog_equipment,
)

logger = logging.getLogger(__name__)


def _resolve_config_path() -> str:
    """Путь к back/project/config.yaml или fallback C:\\temp\\chatbot\\config.yaml."""
    current_file = os.path.abspath(__file__)
    # services -> api -> chatbot -> back -> project
    project_root = os.path.normpath(
        os.path.join(os.path.dirname(current_file), "..", "..", "..", "project")
    )
    config_path = os.path.normpath(os.path.join(project_root, "config.yaml"))
    if os.path.exists(config_path):
        return config_path

    fallback = r"C:\temp\chatbot\config.yaml"
    print(
        f"[WARNING] Project config not found at {config_path}, using: {fallback}"
    )
    return fallback


class RagService:
    """Обёртка над AdvancedChatbot (singleton на уровне процесса Daphne)."""

    def __init__(self) -> None:
        self._bot: Optional[AdvancedChatbot] = None
        self.last_llm_elapsed_ms = 0.0
        self.last_rag_sources: list = []

    def get_bot(self) -> AdvancedChatbot:
        """Lazy init — torch/FAISS грузятся при первом обращении."""
        if self._bot is None:
            config_path = _resolve_config_path()
            print(f"[INFO] RagService: initializing chatbot with config: {config_path}")
            self._bot = AdvancedChatbot(config_path)
        return self._bot

    def answer(self, question: str, chat_id: Optional[int] = None) -> str:
        """RAG-ответ на вопрос пользователя."""
        if chat_id is not None:
            print(f"[DEBUG] RagService.answer chat_id={chat_id}")

        text = (question or "").strip()

        if chat_id is not None:
            handled, reply = self._handle_verification_equipment_reply(text, chat_id)
            if handled:
                return reply
            text = self._inject_stored_verification_equipment(text, chat_id)

        effective = self._resolve_effective_question(text, chat_id)
        if effective != text:
            print(f"[DEBUG] RagService: follow-up merged -> {effective!r}")

        bot = self.get_bot()
        response = bot.generate_response(effective)
        self.last_llm_elapsed_ms = getattr(bot, "last_llm_elapsed_ms", 0.0) or 0.0
        self.last_rag_sources = list(getattr(bot, "last_rag_sources", []) or [])
        return response

    def _handle_verification_equipment_reply(
        self,
        text: str,
        chat_id: int,
    ) -> Tuple[bool, str]:
        """Ответ пользователя с моделью после уточнения по поверке."""
        if not self._awaiting_verification_equipment_name(chat_id, text):
            return False, ""

        bot = self.get_bot()
        found, product_name = resolve_catalog_equipment(text, bot.product_detector)
        if not found:
            return True, VERIFICATION_EQUIPMENT_NOT_FOUND

        equipment_label = (product_name or text).strip()
        self._save_verification_equipment(chat_id, equipment_label)

        original = self._find_pending_verification_question(chat_id, text)
        if original:
            merged = merge_verification_followup(original, equipment_label)
        else:
            merged = merge_verification_followup(
                f"поверка {equipment_label}",
                equipment_label,
            )

        response = bot.generate_response(merged)
        self.last_llm_elapsed_ms = getattr(bot, "last_llm_elapsed_ms", 0.0) or 0.0
        self.last_rag_sources = list(getattr(bot, "last_rag_sources", []) or [])
        return True, response

    def _awaiting_verification_equipment_name(self, chat_id: int, current_text: str) -> bool:
        bot_msg = self._recent_bot_message(chat_id, current_text)
        if bot_msg is None:
            return False
        bot_text = (bot_msg.content or "").strip()
        return (
            VERIFICATION_EQUIPMENT_CLARIFY[:40] in bot_text
            or VERIFICATION_EQUIPMENT_NOT_FOUND[:40] in bot_text
        )

    def _find_pending_verification_question(self, chat_id: int, current_text: str) -> str:
        from ..models import Message

        recent = list(
            Message.objects.filter(chat_id=chat_id).order_by("-created_at")[:12]
        )
        idx = 0
        if recent and recent[0].is_user and (recent[0].content or "").strip() == (current_text or "").strip():
            idx = 1

        for msg in recent[idx:]:
            if not msg.is_user:
                continue
            q = (msg.content or "").strip()
            if q and _is_verification_query(q) and needs_verification_equipment_clarification(q):
                return q
        return ""

    def _inject_stored_verification_equipment(self, text: str, chat_id: int) -> str:
        from ..models import Chat

        if not text or not _is_verification_query(text):
            return text
        if not needs_verification_equipment_clarification(text):
            return text

        chat = Chat.objects.filter(pk=chat_id).only("verification_equipment").first()
        if not chat or not (chat.verification_equipment or "").strip():
            return text

        return inject_verification_equipment(text, chat.verification_equipment)

    @staticmethod
    def _save_verification_equipment(chat_id: int, equipment: str) -> None:
        from ..models import Chat

        Chat.objects.filter(pk=chat_id).update(
            verification_equipment=(equipment or "").strip()[:255]
        )

    def _recent_bot_message(self, chat_id: int, current_user_text: str):
        from ..models import Message

        recent = list(
            Message.objects.filter(chat_id=chat_id).order_by("-created_at")[:8]
        )
        idx = 0
        if recent and recent[0].is_user and (recent[0].content or "").strip() == (current_user_text or "").strip():
            idx = 1
        for msg in recent[idx:]:
            if not msg.is_user:
                return msg
        return None

    def _resolve_effective_question(self, question: str, chat_id: Optional[int]) -> str:
        """
        Если бот просил уточнить модель, а пользователь ответил «UFL» —
        склеиваем с предыдущим вопросом (неисправность или поверка).
        """
        text = (question or "").strip()
        if chat_id is None:
            return text

        if looks_like_verification_equipment_reply(text) and self._awaiting_verification_equipment_name(
            chat_id, text
        ):
            return text

        if not looks_like_equipment_clarification_reply(text):
            return text

        try:
            from ..models import Message

            recent = list(
                Message.objects.filter(chat_id=chat_id).order_by("-created_at")[:8]
            )
        except Exception as exc:
            logger.warning("Cannot load chat history for follow-up: %s", exc)
            return text

        if not recent:
            return text

        idx = 0
        if recent[0].is_user and (recent[0].content or "").strip() == text:
            idx = 1

        bot_msg = None
        prev_user = None
        for msg in recent[idx:]:
            if not msg.is_user and bot_msg is None:
                bot_msg = msg
                continue
            if bot_msg is not None and msg.is_user:
                prev_user = msg
                break

        if bot_msg is None or prev_user is None:
            return text

        bot_text = (bot_msg.content or "").strip()
        prev_q = (prev_user.content or "").strip()
        if not prev_q:
            return text

        if VERIFICATION_EQUIPMENT_CLARIFY[:40] in bot_text and _is_verification_query(prev_q):
            return merge_verification_followup(prev_q, text)

        if TROUBLESHOOTING_EQUIPMENT_CLARIFY[:50] in bot_text and _is_malfunction_query(prev_q):
            return merge_troubleshooting_followup(prev_q, text)

        return text

    def reload(self) -> AdvancedChatbot:
        """Сброс singleton после смены config.yaml или пересборки индекса."""
        self._bot = None
        print("[INFO] RagService: chatbot instance cleared, re-initializing...")
        return self.get_bot()

    def healthcheck(self) -> Dict[str, Any]:
        """Проверка готовности RAG (конфиг, chunks, FAISS, hybrid)."""
        try:
            bot = self.get_bot()
            if bot.config is None:
                return {"ok": False, "reason": "AdvancedChatbot.config is None"}

            store = getattr(bot, "store", None)
            if store is None:
                return {"ok": False, "reason": "VectorStore not loaded"}

            chunks = getattr(store, "chunks", None)
            if not chunks:
                return {"ok": False, "reason": "chunks list is empty"}

            index = getattr(store, "index", None)
            if index is None:
                return {"ok": False, "reason": "FAISS index not loaded"}

            return {
                "ok": True,
                "chunks": len(chunks),
                "faiss_vectors": int(index.ntotal),
                "hybrid_search": getattr(bot, "use_hybrid_search", False),
                "top_k": bot.top_k,
                "threshold": bot.threshold,
                "knowledge_docs": self._knowledge_stats(),
            }
        except Exception as exc:
            logger.exception("RagService healthcheck failed")
            return {"ok": False, "reason": str(exc)}

    @staticmethod
    def _knowledge_stats() -> Dict[str, int]:
        try:
            from ..models import KnowledgeDocument

            qs = KnowledgeDocument.objects.filter(is_active=True)
            return {
                "active": qs.count(),
                "gost": qs.filter(doc_type=KnowledgeDocument.DOC_TYPE_GOST).count(),
                "passport": qs.filter(doc_type=KnowledgeDocument.DOC_TYPE_PASSPORT).count(),
                "catalog": qs.filter(doc_type=KnowledgeDocument.DOC_TYPE_CATALOG).count(),
            }
        except Exception:
            return {"active": 0, "gost": 0, "passport": 0, "catalog": 0}


rag_service = RagService()

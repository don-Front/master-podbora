"""RAG-сервис: инициализация чатбота, ответы, healthcheck."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..chatbot_core import AdvancedChatbot


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
        bot = self.get_bot()
        text = bot.generate_response(question)
        self.last_llm_elapsed_ms = getattr(bot, "last_llm_elapsed_ms", 0.0) or 0.0
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
            return {"ok": False, "reason": str(exc)}

    @staticmethod
    def _knowledge_stats() -> dict:
        try:
            from .knowledge_version import KnowledgeVersionService

            return KnowledgeVersionService.stats()
        except Exception:
            return {"total": 0, "active": 0, "inactive": 0}


rag_service = RagService()

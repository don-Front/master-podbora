"""
Интеграционные тесты RAG-пайплайна (RAG_REFACTOR_PLAN §5.1).

Запуск:
  cd back/chatbot
  py manage.py test tests.test_rag_pipeline -v 2

Требования: собранные data/chunks.json и data/faiss_index.bin (python build.py).
LM Studio не нужна — LLM мокируется в тестах ответа.
"""

from __future__ import annotations

import os
import re
import unittest
from unittest.mock import patch

from django.test import TestCase

from api.chatbot_core.chatbot import (
    AdvancedChatbot,
    adjust_search_parameters,
    smart_search,
)
from api.chatbot_core.llm_client import LLMClient

# --- пути к KB ---

_BACK_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_PROJECT_DIR = os.path.join(_BACK_ROOT, "project")
_CONFIG_PATH = os.path.join(_PROJECT_DIR, "config.yaml")
_CHUNKS_PATH = os.path.join(_PROJECT_DIR, "data", "chunks.json")
_INDEX_PATH = os.path.join(_PROJECT_DIR, "data", "faiss_index.bin")

RAG_INDEX_READY = (
    os.path.isfile(_CONFIG_PATH)
    and os.path.isfile(_CHUNKS_PATH)
    and os.path.isfile(_INDEX_PATH)
)

# --- фикстуры ---

GOST_2939_CHUNK = {
    "chunk_id": "test_gost_2939_p12",
    "product_title": "ГОСТ 2939-63",
    "chunk_type": "gost",
    "content": (
        "ГОСТ 2939-63 «Газ природный. Методы определения содержания воды». "
        "Настоящий стандарт распространяется на природный газ и устанавливает "
        "методы определения содержания воды и влажности газа."
    ),
    "metadata": {
        "document_name": "ГОСТ 2939-63",
        "doc_type": "gost",
        "page_number": 12,
        "knowledge_doc_key": "gost:GOST_2939-63.pdf",
    },
    "score": 0.91,
}

OIL_FLOWMETER_QUESTION = "Подбери расходомер для нефти, класс точности 0,1%"
GOST_HUMIDITY_QUESTION = "Какой ГОСТ регламентирует влажность газа?"


def _citation_pattern() -> re.Pattern[str]:
    return re.compile(r"\[Документ:\s*.+?\]")


@unittest.skipUnless(RAG_INDEX_READY, "Нет config.yaml / chunks.json / faiss_index.bin")
class RagPipelineIntegrationTests(TestCase):
    """Retrieval + generate_response с моком LLM."""

    _bot: AdvancedChatbot | None = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._bot = AdvancedChatbot(_CONFIG_PATH)
        if cls._bot.config is None:
            raise unittest.SkipTest("AdvancedChatbot не инициализировался (config/index)")

    @classmethod
    def tearDownClass(cls):
        cls._bot = None
        super().tearDownClass()

    def setUp(self):
        self.bot = self._bot
        assert self.bot is not None

    def test_retrieval_oil_flowmeter_finds_relevant_product(self):
        """Поиск по нефти и точности 0,1% находит CFM-ULG / UFL в топе."""
        question_type = self.bot.classifier.classify(OIL_FLOWMETER_QUESTION)
        search_params = adjust_search_parameters(
            question_type, self.bot.top_k, self.bot.threshold
        )
        query_embedding = self.bot.embedder.encode(OIL_FLOWMETER_QUESTION)
        results = smart_search(
            self.bot.store,
            self.bot.product_detector,
            query_embedding,
            OIL_FLOWMETER_QUESTION,
            search_params,
            question_type,
            hybrid_retriever=self.bot.hybrid,
            use_hybrid=True,
        )
        self.assertGreater(len(results), 0, "Поиск не вернул чанков")

        top_text = " ".join(
            (r.get("product_title") or "") + " " + (r.get("content") or "")
            for r in results[:8]
        ).lower()
        has_oil = "нефт" in top_text
        has_model = "cfm" in top_text or "ufl" in top_text or "turbo flow" in top_text
        has_accuracy = "0,1" in top_text or "0.1" in top_text or "0,1-" in top_text

        self.assertTrue(has_oil, "В топе нет упоминания нефти")
        self.assertTrue(has_model, "В топе нет модели расходомера (CFM/UFL/Turbo Flow)")
        self.assertTrue(has_accuracy, "В топе нет класса точности 0,1%")

    @patch.object(AdvancedChatbot, "is_greeting", return_value=False)
    @patch("api.chatbot_core.chatbot.smart_search")
    def test_oil_flowmeter_answer_has_model_and_citation(self, mock_search, _mock_greeting):
        """Ответ содержит рекомендацию модели и ссылку на источник."""
        cfm_chunk = next(
            (
                c
                for c in self.bot.store.chunks
                if "cfm-ulg" in (c.get("product_title") or "").lower()
            ),
            self.bot.store.chunks[0],
        )
        cfm_chunk = dict(cfm_chunk)
        cfm_chunk["score"] = 0.95
        mock_search.return_value = [cfm_chunk]

        def fake_generate(chunks, question, question_type):
            title = chunks[0].get("product_title") or "Turbo Flow CFM-ULG"
            cite = LLMClient._resolve_chunk_source(chunks[0])["citation"]
            return (
                f"Для учёта нефти рекомендуем {title} с точностью до 0,1%. {cite}"
            )

        self.bot.llm.generate = fake_generate
        answer = self.bot.generate_response(OIL_FLOWMETER_QUESTION)

        self.assertNotIn("Не удалось найти", answer)
        self.assertRegex(answer, r"CFM|UFL|Turbo Flow", msg=answer)
        self.assertRegex(answer, _citation_pattern(), msg=answer)

    @patch.object(AdvancedChatbot, "is_greeting", return_value=False)
    @patch("api.chatbot_core.chatbot.smart_search")
    def test_gost_humidity_answer_contains_gost_number(self, mock_search, _mock_greeting):
        """При наличии чанка ГОСТ 2939-63 ответ содержит номер стандарта."""
        mock_search.return_value = [GOST_2939_CHUNK]

        def fake_generate(chunks, question, question_type):
            cite = LLMClient._resolve_chunk_source(chunks[0])["citation"]
            return (
                "Влажность природного газа регламентирует ГОСТ 2939-63. "
                f"{cite}"
            )

        self.bot.llm.generate = fake_generate
        answer = self.bot.generate_response(GOST_HUMIDITY_QUESTION)

        self.assertIn("ГОСТ 2939-63", answer)
        self.assertRegex(answer, _citation_pattern(), msg=answer)

    def test_build_context_includes_source_citation_block(self):
        """Контекст для LLM содержит блок «Ссылка для ответа»."""
        sample = self.bot.store.chunks[0]
        sample = dict(sample)
        sample["score"] = 0.88
        context = LLMClient.build_context([sample])
        self.assertIn("Ссылка для ответа:", context)
        self.assertIn("[Документ:", context)
        self.assertIn("Документ:", context)

    def test_resolve_chunk_source_catalog_chunk(self):
        """Цитирование каталожного чанка с document_name в metadata."""
        chunk = dict(self.bot.store.chunks[0])
        meta = dict(chunk.get("metadata") or {})
        meta.setdefault("document_name", chunk.get("product_title", "Тест"))
        meta.setdefault("doc_type", "catalog")
        chunk["metadata"] = meta

        src = LLMClient._resolve_chunk_source(chunk)
        self.assertNotEqual(src["document_name"], "не указан")
        self.assertTrue(src["citation"].startswith("[Документ:"))


class RagPipelineUnitTests(TestCase):
    """Без FAISS — только формат цитирования."""

    def test_gost_chunk_citation_with_page(self):
        src = LLMClient._resolve_chunk_source(GOST_2939_CHUNK)
        self.assertEqual(src["document_name"], "ГОСТ 2939-63")
        self.assertIn("стр. 12", src["citation"])

    def test_build_context_for_gost_chunk(self):
        context = LLMClient.build_context([GOST_2939_CHUNK])
        self.assertIn("ГОСТ 2939-63", context)
        self.assertIn("стр. 12", context)


@unittest.skipUnless(RAG_INDEX_READY, "Нет faiss_index.bin")
class RagKnowledgeGapTests(TestCase):
    """Документирует пробел KB: ГОСТ 2939-63 отсутствует в текущем каталоге."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import json

        with open(_CHUNKS_PATH, encoding="utf-8") as fh:
            chunks = json.load(fh).get("chunks") or []
        cls._kb_has_gost_2939 = any(
            "2939-63" in (c.get("content") or "") for c in chunks
        )

    def test_kb_may_lack_gost_2939(self):
        if self._kb_has_gost_2939:
            self.skipTest("ГОСТ 2939-63 уже есть в chunks.json")
        self.assertFalse(
            self._kb_has_gost_2939,
            "Ожидался пробел KB — добавьте documents/gost/ и пересоберите индекс",
        )

"""Тесты улучшений RAG: multi-product и виджет источников."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from django.test import SimpleTestCase

from api.chatbot_core.chatbot import AdvancedChatbot, smart_search, adjust_search_parameters
from api.chatbot_core.product_detector import ProductDetector
from api.chatbot_core.rag_sources import (
    build_rag_sources,
    filter_source_chunks,
    strip_inline_citations,
)
from api.chatbot_core.product_detector import (
    looks_like_equipment_clarification_reply,
    merge_troubleshooting_followup,
    needs_troubleshooting_equipment_clarification,
)
from api.chatbot_core.query_rewrite import rewrite_rag_question

_BACK_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PROJECT_DIR = os.path.join(_BACK_ROOT, "project")
_CONFIG_PATH = os.path.join(_PROJECT_DIR, "config.yaml")
_CHUNKS_PATH = os.path.join(_PROJECT_DIR, "data", "chunks.json")
_INDEX_PATH = os.path.join(_PROJECT_DIR, "data", "faiss_index.bin")

RAG_INDEX_READY = (
    os.path.isfile(_CONFIG_PATH)
    and os.path.isfile(_CHUNKS_PATH)
    and os.path.isfile(_INDEX_PATH)
)

UFG_TFG_QUESTION = (
    "Под какие диапазоны давления существуют серия расходомеров UFG и TFG?"
)


class RagSourcesHelpersTest(SimpleTestCase):
    def test_strip_inline_citations(self):
        raw = (
            "Исполнение A до 1,6 МПа [Документ: !РЭ на TFG, стр. 8]; "
            "исполнение B до 6,3 МПа [Документ: !РЭ на TFG, стр. 8]."
        )
        cleaned = strip_inline_citations(raw)
        self.assertNotIn("[Документ:", cleaned)
        self.assertIn("1,6 МПа", cleaned)

    def test_build_rag_sources_deduplicates(self):
        chunks = [
            {
                "chunk_id": "a",
                "product_title": "Turbo Flow TFG",
                "score": 0.9,
                "metadata": {
                    "document_name": "!РЭ на TFG",
                    "page_number": 8,
                    "url": "https://example.com/tfg.pdf",
                },
            },
            {
                "chunk_id": "b",
                "product_title": "Turbo Flow TFG",
                "score": 0.85,
                "metadata": {
                    "document_name": "!РЭ на TFG",
                    "page_number": 8,
                    "url": "https://example.com/tfg.pdf",
                },
            },
        ]
        sources = build_rag_sources(chunks)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["title"], "!РЭ на TFG")
        self.assertTrue(sources[0]["actions"][0]["href"].startswith("https://"))

    def test_build_rag_sources_groups_pages_into_one_widget(self):
        chunks = [
            {
                "chunk_id": "p1",
                "product_title": "ОТ Гранд",
                "score": 0.8,
                "metadata": {
                    "document_name": "ОТ Гранд (изм адр 2024)",
                    "page_number": 1,
                    "url": "https://example.com/ot_grand.pdf",
                },
            },
            {
                "chunk_id": "p2",
                "product_title": "ОТ Гранд",
                "score": 0.75,
                "metadata": {
                    "document_name": "ОТ Гранд (изм адр 2024)",
                    "page_number": 2,
                    "url": "https://example.com/otgrand.pdf",
                },
            },
            {
                "chunk_id": "p5",
                "product_title": "ОТ Гранд",
                "score": 0.7,
                "metadata": {
                    "document_name": "ОТ Гранд (изм адр 2024)",
                    "page_number": 5,
                    "url": "https://example.com/ot_grand.pdf",
                },
            },
        ]
        sources = build_rag_sources(chunks)
        self.assertEqual(len(sources), 1)
        self.assertIn("стр. 1", sources[0]["description"])
        self.assertIn("5", sources[0]["description"])
        self.assertEqual(sources[0]["actions"][0]["label"], "Открыть «ОТ Гранд (изм адр 2024)»")

    def test_filter_source_chunks_by_answer_series(self):
        ufg_chunk = {
            "product_title": "Turbo Flow UFG",
            "score": 0.9,
            "metadata": {"document_name": "РЭ UFG-H (акт)", "page_number": 116},
            "content": "UFG индикация",
        }
        tfg_chunk = {
            "product_title": "Turbo Flow TFG",
            "score": 0.88,
            "metadata": {"document_name": "!РЭ на TFG", "page_number": 52},
            "content": "TFG неисправности",
        }
        filtered = filter_source_chunks(
            [ufg_chunk, tfg_chunk],
            question="оборвался провод",
            answer="На Turbo Flow UFG обрыв питающего провода может вызвать отсутствие индикации.",
        )
        titles = [c["metadata"]["document_name"] for c in filtered]
        self.assertEqual(titles, ["РЭ UFG-H (акт)"])

    def test_needs_troubleshooting_equipment_clarification(self):
        q = "у меня оборвался питающий провод, что это за неисправность"
        self.assertTrue(needs_troubleshooting_equipment_clarification(q, []))
        # Embedding «угадал» UFG — всё равно уточняем, в тексте модели нет
        self.assertTrue(
            needs_troubleshooting_equipment_clarification(
                "не работает индикатор что делать",
                [("Turbo Flow UFG", 0.9)],
            )
        )
        self.assertFalse(
            needs_troubleshooting_equipment_clarification(
                "на UFG нет индикации, что за неисправность",
                [],
            )
        )

    def test_equipment_clarification_followup_helpers(self):
        self.assertTrue(looks_like_equipment_clarification_reply("UFL"))
        self.assertFalse(
            looks_like_equipment_clarification_reply("на UFL не работает катушка")
        )
        merged = merge_troubleshooting_followup(
            "у меня не работает катушка",
            "UFL",
        )
        self.assertIn("катушка", merged)
        self.assertIn("UFL", merged)

    def test_rewrite_medium_question(self):
        rewritten = rewrite_rag_question("какая среда у UFG а какая у UFL")
        self.assertIn("измеряемая среда", rewritten.casefold())
        self.assertIn("газ", rewritten.casefold())
        self.assertNotEqual(rewritten, "какая среда у UFG а какая у UFL")


@unittest.skipUnless(RAG_INDEX_READY, "Нет config.yaml / chunks.json / faiss_index.bin")
class RagMultiProductTest(unittest.TestCase):
    _bot: AdvancedChatbot | None = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._bot = AdvancedChatbot(_CONFIG_PATH)
        if cls._bot.config is None:
            raise unittest.SkipTest("AdvancedChatbot не инициализировался")

    @classmethod
    def tearDownClass(cls):
        cls._bot = None
        super().tearDownClass()

    def test_detect_two_products_from_question(self):
        bot = self._bot
        assert bot is not None
        products = bot.product_detector.detect_products_from_question(UFG_TFG_QUESTION)
        self.assertGreaterEqual(len(products), 2, products)
        joined = " ".join(name.lower() for name, _ in products)
        self.assertIn("ufg", joined.replace("-", " "))
        self.assertIn("tfg", joined.replace("-", " "))

    def test_smart_search_includes_both_series(self):
        bot = self._bot
        assert bot is not None
        question_type = bot.classifier.classify(UFG_TFG_QUESTION)
        detected = bot.product_detector.detect_products_from_question(UFG_TFG_QUESTION)
        if len(detected) >= 2:
            question_type = dict(question_type)
            question_type["detected_products"] = [name for name, _ in detected]

        search_params = adjust_search_parameters(question_type, bot.top_k, bot.threshold)
        query_embedding = bot.embedder.encode(UFG_TFG_QUESTION)
        results = smart_search(
            bot.store,
            bot.product_detector,
            query_embedding,
            UFG_TFG_QUESTION,
            search_params,
            question_type,
            hybrid_retriever=bot.hybrid,
            use_hybrid=True,
        )
        self.assertGreater(len(results), 0)
        blob = " ".join(
            (r.get("product_title") or "") + " " + (r.get("content") or "")
            for r in results[:12]
        ).lower()
        has_ufg = "ufg" in blob
        has_tfg = "tfg" in blob
        self.assertTrue(has_ufg or has_tfg, "В топе нет UFG/TFG")
        if len(detected) >= 2:
            self.assertTrue(has_ufg and has_tfg, f"Ожидались обе серии, blob={blob[:200]}")

    @patch.object(AdvancedChatbot, "is_greeting", return_value=False)
    def test_generate_response_sets_sources_without_inline_citations(self, _mock_greeting):
        bot = self._bot
        assert bot is not None

        ufg_chunk = next(
            (
                dict(c)
                for c in bot.store.chunks
                if "ufg" in (c.get("product_title") or "").lower()
                and (c.get("metadata") or {}).get("document_name")
            ),
            None,
        )
        tfg_chunk = next(
            (
                dict(c)
                for c in bot.store.chunks
                if "tfg" in (c.get("product_title") or "").lower()
                and (c.get("metadata") or {}).get("document_name")
            ),
            None,
        )
        self.assertIsNotNone(ufg_chunk)
        self.assertIsNotNone(tfg_chunk)
        ufg_chunk["score"] = 0.93
        tfg_chunk["score"] = 0.91

        def fake_generate(chunks, question, question_type):
            return (
                "**Turbo Flow UFG:** диапазоны давления …\n\n"
                "**Turbo Flow TFG:** исполнения A–E до 32 МПа."
            )

        with patch("api.chatbot_core.chatbot.smart_search", return_value=[ufg_chunk, tfg_chunk]):
            bot.llm.generate = fake_generate
            answer = bot.generate_response(UFG_TFG_QUESTION)

        self.assertNotIn("[Документ:", answer)
        self.assertGreaterEqual(len(bot.last_rag_sources), 1)

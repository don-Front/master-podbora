from django.test import SimpleTestCase

from api.chatbot_core.chatbot import _has_document_reference
from api.chatbot_core.product_detector import ProductDetector


class _Store:
    active_doc_keys = None
    chunks = [
        {
            "chunk_id": "ufg-power",
            "product_title": "Turbo Flow UFG-Н",
            "chunk_type": "passport",
            "content": "Turbo Flow UFG-Н питание от батареи 3,6 В и внешнего блока 12-24 В.",
            "metadata": {},
        },
        {
            "chunk_id": "ufg-mount",
            "product_title": "Turbo Flow UFG-Н",
            "chunk_type": "passport",
            "content": "Turbo Flow UFG-Н монтаж выполняется при отсутствии давления.",
            "metadata": {},
        },
    ]


class _ProductStore:
    active_doc_keys = None
    chunks = [
        {
            "chunk_id": "ufg-h",
            "product_title": "Ультразвуковой расходомер-счетчик газа Turbo Flow UFG-H",
            "chunk_type": "catalog",
            "content": "Turbo Flow UFG-H",
            "metadata": {},
        },
        {
            "chunk_id": "gfg-f",
            "product_title": "Расходомер Turbo Flow GFG-F для технических газов",
            "chunk_type": "catalog",
            "content": "Turbo Flow GFG-F",
            "metadata": {},
        },
    ]


class _MetadataProductStore:
    active_doc_keys = None
    chunks = [
        {
            "chunk_id": "passport-cfm",
            "product_title": "",
            "chunk_type": "passport",
            "content": "Turbo Flow CFM кориолисовый массовый расходомер для нефти.",
            "metadata": {
                "doc_type": "passport",
                "product_title": "Turbo Flow CFM",
                "product_family": "CFM",
                "source_file": "РЭ СFМ (акт).pdf",
            },
        },
        {
            "chunk_id": "catalog-cfm",
            "product_title": "Turbo Flow CFM",
            "chunk_type": "specifications",
            "content": "Краткое описание CFM из каталога.",
            "metadata": {"doc_type": "catalog"},
        },
    ]


class _NoRuntimeEncode:
    def encode(self, _text):
        raise AssertionError("search_chunks_by_product не должен кодировать content чанков")


class ProductDetectorSearchTests(SimpleTestCase):
    def test_product_search_does_not_encode_chunk_content(self):
        detector = ProductDetector(_Store(), _NoRuntimeEncode())

        results = detector.search_chunks_by_product(
            "Turbo Flow UFG-Н", top_k=2, query_text="Какие параметры питания?"
        )

        self.assertEqual(results[0]["chunk_id"], "ufg-power")
        self.assertEqual(len(results), 2)

    def test_cyrillic_ufg_h_matches_latin_product_title(self):
        detector = ProductDetector(_ProductStore(), _NoRuntimeEncode())

        product, score = detector.detect_product_from_question(
            "Какие питание, интерфейсы и DN указаны для Turbo Flow UFG-Н?"
        )

        self.assertIn("UFG-H", product)
        self.assertGreaterEqual(score, 0.9)

    def test_document_reference_is_detected(self):
        self.assertTrue(_has_document_reference("Что описывает ГОСТ 8.741-2019?"))
        self.assertTrue(_has_document_reference("Требования СТО Газпром 5.37-2020"))
        self.assertTrue(_has_document_reference("Что указано в описании типа 56432-14?"))
        self.assertTrue(_has_document_reference("Что написано в руководстве по эксплуатации UFL?"))
        self.assertFalse(_has_document_reference("Какие интерфейсы у Turbo Flow UFG-Н?"))

    def test_product_search_uses_metadata_product_title_and_boosts_passport(self):
        detector = ProductDetector(_MetadataProductStore(), _NoRuntimeEncode())

        results = detector.search_chunks_by_product(
            "Turbo Flow CFM", top_k=2, query_text="Какая погрешность у CFM?"
        )

        self.assertEqual(results[0]["chunk_id"], "passport-cfm")
        self.assertEqual(results[0]["metadata"]["source_file"], "РЭ СFМ (акт).pdf")

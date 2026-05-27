"""Юнит-тесты детектора интента подбора оборудования по свободному тексту."""

from django.test import SimpleTestCase

from api.order_specs_text import looks_like_order_specs_request


class OrderSpecsIntentTest(SimpleTestCase):
    def test_no_selection_keyword_goes_to_rag(self):
        msg = (
            "Нужен расходомер для учета сжиженного газа на заправке с низкой вязкостью. "
            "Какие параметры нужно уточнить?"
        )
        self.assertFalse(looks_like_order_specs_request(msg))

    def test_selection_keyword_triggers_flow(self):
        self.assertTrue(
            looks_like_order_specs_request("Подберите расходомер для учета сжиженного газа на заправке")
        )
        self.assertTrue(
            looks_like_order_specs_request("Нужен подбор расходомера DN50, газ, 1.6 МПа")
        )
        self.assertTrue(
            looks_like_order_specs_request("Помогите подобрать оборудование для измерения расхода газа")
        )

    def test_short_or_empty(self):
        self.assertFalse(looks_like_order_specs_request("подбор"))
        self.assertFalse(looks_like_order_specs_request(""))

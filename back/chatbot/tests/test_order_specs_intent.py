"""Юнит-тесты детектора интента подбора оборудования по свободному тексту."""

from django.test import SimpleTestCase

from api.order_specs_helpers import build_order_specs_review_rows, list_missing_fields
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


class OrderSpecsOptionalFieldsTest(SimpleTestCase):
    def test_gas_type_is_optional_for_selection(self):
        draft = {
            "medium": "gas",
            "gas_type": None,
            "flowMin": 10,
            "flowMax": 500,
            "flow_unit": "ст.м³/ч",
            "pressureMin": 0.1,
            "pressureMax": 1.6,
            "pressure_unit": "МПа",
            "tempMediumMin": -10,
            "tempMediumMax": 30,
            "tempAmbientMin": -40,
            "tempAmbientMax": 40,
            "temperature_unit": "°C",
            "accuracy": "1%",
            "diameter": 100,
        }

        self.assertNotIn("gas_type", list_missing_fields(draft))

        gas_type_row = next(
            row for row in build_order_specs_review_rows(draft) if row["key"] == "gas_type"
        )
        self.assertEqual(gas_type_row["label"], "Тип газа (необязательно)")
        self.assertEqual(gas_type_row["value"], "")

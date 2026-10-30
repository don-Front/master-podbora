"""Тесты маппинга масок конкурентов в параметры search-equipment."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from api.competitor_masks import competitor_mask_decoder
from api.competitor_masks.analog_mapper import ANALOG_INTRO, build_analog_search_specs
from api.competitor_masks.comparison_builder import build_competitor_comparison_card
from api.services.competitor_mask_service import apply_to_context
from api.services.message_flow_context import MessageFlowContext


class IrvisAnalogMapperTests(SimpleTestCase):
    def test_valid_mask_maps_pressure_dn_flow_accuracy(self) -> None:
        result = competitor_mask_decoder.decode("ИРВИС-Ультра-Пп-16-DN200-100-ГОТ")
        self.assertTrue(result.is_valid)
        analog = build_analog_search_specs(result.catalog_id, result.parsed_fields, is_valid=True)
        self.assertIsNotNone(analog.specs)
        self.assertEqual(analog.specs.get("flowMax"), 100)
        self.assertEqual(analog.specs.get("diameter"), 200)
        self.assertEqual(analog.specs.get("pressureMax"), 1.6)
        self.assertEqual(analog.specs.get("accuracy"), "1")
        self.assertEqual(analog.specs.get("medium"), "gas")

    def test_invalid_mask_skips_analogs(self) -> None:
        result = competitor_mask_decoder.decode("ИРВИС-Ультра-Пп-12-DN200-100-ГОТ")
        self.assertFalse(result.is_valid)
        analog = build_analog_search_specs(result.catalog_id, result.parsed_fields, is_valid=False)
        self.assertIsNone(analog.specs)
        self.assertEqual(analog.skip_reason, "mask_has_validation_errors")


class RgTAnalogMapperTests(SimpleTestCase):
    def test_valid_mask_maps_g_size_and_pn(self) -> None:
        result = competitor_mask_decoder.decode("РГ-Т-G400-DN100-PN16-О")
        self.assertTrue(result.is_valid)
        analog = build_analog_search_specs(result.catalog_id, result.parsed_fields, is_valid=True)
        self.assertIsNotNone(analog.specs)
        self.assertEqual(analog.specs.get("flowMax"), 650)
        self.assertEqual(analog.specs.get("diameter"), 100)
        self.assertEqual(analog.specs.get("pressureMax"), 1.6)
        self.assertEqual(analog.specs.get("accuracy"), "1")


class CompetitorAnalogFlowTests(SimpleTestCase):
    def test_apply_to_context_sets_analog_specs(self) -> None:
        ctx = MessageFlowContext(
            chat_id=1,
            request_data={},
            question="ИРВИС-Ультра-Пп-16-DN200-100-ГОТ",
            current_state="start",
            is_hint_selection=False,
            hint_locked=False,
            state_data={},
            is_start_like=True,
        )
        handled = apply_to_context(ctx)
        self.assertTrue(handled)
        self.assertIsInstance(ctx.competitor_analog_specs, dict)
        self.assertEqual(ctx.competitor_analog_intro, ANALOG_INTRO)
        self.assertEqual(ctx.competitor_analog_specs.get("flowMax"), 100)
        self.assertEqual(ctx.next_state, "order_final")
        self.assertIsInstance(ctx.order_specs_json, dict)
        self.assertEqual(ctx.order_specs_json.get("flowMax"), 100)

    def test_apply_to_context_sets_comparison_card(self) -> None:
        ctx = MessageFlowContext(
            chat_id=1,
            request_data={},
            question="ИРВИС-Ультра-Пп-16-DN200-100-ГОТ",
            current_state="start",
            is_hint_selection=False,
            hint_locked=False,
            state_data={},
            is_start_like=True,
        )
        handled = apply_to_context(ctx)
        self.assertTrue(handled)
        card = ctx.competitor_comparison_card
        self.assertIsInstance(card, dict)
        self.assertEqual(card.get("catalog_id"), "irvis_ultra")
        self.assertGreaterEqual(len(card.get("rows") or []), 3)
        self.assertIn("turbo_slide", card)


class CompetitorComparisonBuilderTests(SimpleTestCase):
    def test_irvis_comparison_has_advantage_rows(self) -> None:
        card = build_competitor_comparison_card("irvis_ultra")
        self.assertIsNotNone(card)
        assert card is not None
        self.assertEqual(card["competitor_name"], "ИРВИС-Ультра")
        labels = [row["label"] for row in card["rows"]]
        self.assertIn("Диаметры, DN", labels)
        self.assertIn("Давление", labels)
        self.assertTrue(card["turbo_slide"]["highlights"])

    def test_unknown_catalog_returns_none(self) -> None:
        self.assertIsNone(build_competitor_comparison_card("unknown_vendor"))


class CompetitorAnalogApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        response = self.client.post("/api/chats/", {"title": "Competitor analog"})
        self.assertEqual(response.status_code, 201)
        self.chat_id = response.data["id"]

    def post_message(self, content: str) -> object:
        return self.client.post(
            f"/api/chats/{self.chat_id}/messages/",
            {
                "content": content,
                "hint_state": "start",
                "hint_locked": False,
                "is_hint_selection": False,
            },
            format="json",
        )

    def test_api_returns_analog_specs_for_valid_irvis(self) -> None:
        response = self.post_message("ИРВИС-Ультра-Пп-16-DN200-100-ГОТ")
        self.assertEqual(response.status_code, 201)
        specs = response.data.get("competitor_analog_specs")
        self.assertIsInstance(specs, dict)
        self.assertEqual(specs.get("diameter"), 200)
        self.assertEqual(response.data.get("competitor_analog_intro"), ANALOG_INTRO)
        comparison = response.data.get("competitor_comparison_card")
        self.assertIsInstance(comparison, dict)
        self.assertEqual(comparison.get("catalog_id"), "irvis_ultra")
        self.assertGreaterEqual(len(comparison.get("rows") or []), 3)
        self.assertEqual(response.data["hint_state"]["current_state"], "order_final")
        order_specs = response.data.get("order_specs_json")
        self.assertIsInstance(order_specs, dict)
        self.assertEqual(order_specs.get("diameter"), 200)

    def test_api_skips_analog_specs_for_invalid_irvis(self) -> None:
        response = self.post_message("ИРВИС-Ультра-Пп-12-DN200-100-ГОТ")
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data.get("competitor_analog_specs"))

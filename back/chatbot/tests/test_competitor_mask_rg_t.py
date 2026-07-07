"""Тесты расшифровки маски РГ-Т."""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from api.competitor_masks import competitor_mask_decoder
from api.competitor_masks.service import format_decode_response
from api.services.competitor_mask_service import apply_to_context
from api.services.message_flow_context import MessageFlowContext


class RgTMaskParserTests(SimpleTestCase):
    def test_valid_mask_decodes_all_fields(self) -> None:
        result = competitor_mask_decoder.decode("РГ-Т-G400-DN100-PN16-О")
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.competitor, "РГ-Т")
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(
            values,
            {"size": "G400", "dn": "DN100", "pn": "PN16", "metrology": "О"},
        )

    def test_invalid_size_lists_allowed_values(self) -> None:
        result = competitor_mask_decoder.decode("РГ-Т-G163-DN100-PN16-О")
        self.assertTrue(result.handled)
        self.assertFalse(result.is_valid)
        self.assertEqual(len(result.errors), 1)
        err = result.errors[0]
        self.assertEqual(err.field_id, "size")
        self.assertEqual(err.raw_value, "G163")
        self.assertIn("G160", err.allowed)
        self.assertIn("G250", err.allowed)
        self.assertNotIn("G163", err.allowed)

        text = format_decode_response(result)
        self.assertIn("G163", text)
        self.assertIn("G160", text)
        self.assertIn("G250", text)
        self.assertIn("DN100", text)

    def test_latin_aliases_for_metrology(self) -> None:
        result = competitor_mask_decoder.decode("RG-T-G400-DN100-PN16-2Y")
        self.assertTrue(result.is_valid)
        metrology = next(field for field in result.parsed_fields if field.field_id == "metrology")
        self.assertEqual(metrology.value, "2У")

    def test_normal_question_is_not_mask(self) -> None:
        self.assertFalse(
            competitor_mask_decoder.looks_like_mask(
                "Какой расходомер Turbo Flow UFG подойдёт для DN100?"
            )
        )


class CompetitorMaskFlowTests(SimpleTestCase):
    def test_apply_to_context_bypasses_rag(self) -> None:
        ctx = MessageFlowContext(
            chat_id=1,
            request_data={},
            question="РГ-Т-G400-DN100-PN16-О",
            current_state="start",
            is_hint_selection=False,
            hint_locked=False,
            state_data={},
            is_start_like=True,
        )
        handled = apply_to_context(ctx)
        self.assertTrue(handled)
        self.assertEqual(ctx.bot_response, "")
        self.assertTrue(ctx.allow_empty_bot)
        self.assertEqual(ctx.next_state, "start")
        self.assertEqual(ctx.rag_llm_ms, 0.0)
        self.assertIsInstance(ctx.competitor_mask_card, dict)
        self.assertEqual(ctx.competitor_mask_card.get("catalog_id"), "rg_t")
        self.assertEqual(ctx.competitor_mask_card.get("image"), "rg_t.png")
        self.assertTrue(ctx.competitor_mask_card.get("parameters"))
        self.assertTrue(ctx.competitor_mask_card.get("is_valid"))


class CompetitorMaskApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        response = self.client.post("/api/chats/", {"title": "Competitor mask"})
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

    def test_api_valid_mask_response(self) -> None:
        response = self.post_message("РГ-Т-G400-DN100-PN16-О")
        self.assertEqual(response.status_code, 201)
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertEqual((bot["content"] or "").strip(), "")
        card = response.data.get("competitor_mask_card")
        self.assertIsInstance(card, dict)
        self.assertTrue(card.get("is_valid"))
        self.assertEqual(card.get("catalog_id"), "rg_t")

    def test_api_invalid_size_response(self) -> None:
        response = self.post_message("РГ-Т-G163-DN100-PN16-О")
        self.assertEqual(response.status_code, 201)
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertEqual((bot["content"] or "").strip(), "")
        card = response.data.get("competitor_mask_card")
        self.assertIsInstance(card, dict)
        self.assertFalse(card.get("is_valid"))
        errors = card.get("errors") or []
        self.assertEqual(errors[0].get("field_id"), "size")
        self.assertEqual(errors[0].get("raw_value"), "G163")
        self.assertIn("G160", errors[0].get("allowed") or [])

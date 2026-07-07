# -*- coding: utf-8 -*-
"""Запрос цены со слайдера аналогов конкурента (hint_state start + equipment_for_price)."""

from django.test import TestCase
from rest_framework.test import APIClient


class PriceFlowFromSliderTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        response = self.client.post("/api/chats/", {"title": "Price from slider"})
        self.assertEqual(response.status_code, 201)
        self.chat_id = response.data["id"]

    def post_price_hint(
        self,
        *,
        hint_state: str = "start",
        hint_locked: bool = False,
    ):
        return self.client.post(
            f"/api/chats/{self.chat_id}/messages/",
            {
                "content": "Получить цену",
                "hint_state": hint_state,
                "hint_locked": hint_locked,
                "is_hint_selection": True,
                "equipment_for_price": {
                    "id": "ufg-100",
                    "model": "Turbo Flow UFG-F",
                    "name": "Turbo Flow UFG-F",
                    "image": "",
                },
                "order_specs_for_price": {
                    "flowMax": 650,
                    "diameter": 100,
                    "pressureMax": 1.6,
                    "accuracy": "1",
                    "medium": "gas",
                },
            },
            format="json",
        )

    def test_price_hint_from_start_with_equipment_starts_phone_flow(self) -> None:
        response = self.post_price_hint()
        self.assertEqual(response.status_code, 201)
        hs = response.data["hint_state"]
        self.assertEqual(hs["current_state"], "equipment_price_phone")
        self.assertTrue(hs.get("hint_locked"))
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertIn("телефон", (bot.get("content") or "").casefold())

    def test_price_hint_from_order_final_starts_phone_flow(self) -> None:
        response = self.post_price_hint(hint_state="order_final", hint_locked=True)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["hint_state"]["current_state"],
            "equipment_price_phone",
        )

    def test_price_hint_from_start_without_equipment_stays_in_hints(self) -> None:
        response = self.client.post(
            f"/api/chats/{self.chat_id}/messages/",
            {
                "content": "Получить цену",
                "hint_state": "start",
                "hint_locked": False,
                "is_hint_selection": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(
            response.data["hint_state"]["current_state"],
            "equipment_price_phone",
        )

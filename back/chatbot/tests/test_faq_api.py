from django.test import TestCase
from rest_framework.test import APIClient


class FaqApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        response = self.client.post("/api/chats/", {"title": "FAQ API"})
        self.assertEqual(response.status_code, 201)
        self.chat_id = response.data["id"]

    def post_message(self, content):
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

    def test_faq_link_response_contains_card(self):
        response = self.post_message("Где посмотреть сведения о поверке расходомера?")

        self.assertEqual(response.status_code, 201)
        card = response.data.get("faq_card")
        self.assertIsNotNone(card)
        self.assertIn("поверке", card["title"].lower())
        self.assertEqual(card["actions"][0]["type"], "url")
        self.assertIn("fgis.gost.ru", card["actions"][0]["href"])
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertNotIn("Где посмотреть сведения", bot["content"])

    def test_repair_response_contains_card_and_attachment(self):
        response = self.post_message("Как отправить оборудование для платного или гарантийного ремонта")

        self.assertEqual(response.status_code, 201)
        card = response.data.get("faq_card")
        self.assertIsNotNone(card)
        self.assertEqual(card["actions"][0]["type"], "file")
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertIsNotNone(bot["attachment_url"])
        self.assertIn("Памятка", bot["attachment_name"])

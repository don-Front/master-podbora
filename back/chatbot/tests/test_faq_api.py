from django.test import TestCase
from rest_framework.test import APIClient

from api.services import faq_service


class FaqApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        response = self.client.post("/api/chats/", {"title": "FAQ API"})
        self.assertEqual(response.status_code, 201)
        self.chat_id = response.data["id"]

    def post_message(
        self,
        content,
        *,
        hint_state="start",
        hint_locked=False,
        is_hint_selection=False,
    ):
        return self.client.post(
            f"/api/chats/{self.chat_id}/messages/",
            {
                "content": content,
                "hint_state": hint_state,
                "hint_locked": hint_locked,
                "is_hint_selection": is_hint_selection,
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
        self.assertIn("message-attachments/", bot["attachment_url"])
        self.assertIn("Памятка", bot["attachment_name"])

    def test_repair_attachment_download_endpoint(self):
        response = self.post_message("Как отправить оборудование для платного или гарантийного ремонта")
        self.assertEqual(response.status_code, 201)
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        download = self.client.get(f"/api/{bot['attachment_url']}")
        self.assertEqual(download.status_code, 200)
        body = b"".join(download.streaming_content)
        self.assertGreater(len(body), 0)

    def test_faq_repair_memo_static_endpoint(self):
        response = self.client.get("/api/faq-attachments/repair-memo/")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content)
        self.assertGreater(len(body), 0)

    def test_repair_card_has_static_faq_href(self):
        response = self.post_message("Как отправить оборудование для платного или гарантийного ремонта")
        card = response.data.get("faq_card")
        self.assertIsNotNone(card)
        self.assertEqual(card["actions"][0]["href"], "faq-attachments/repair-memo/")

    def test_repair_equipment_list_returns_personal_cabinet_card(self):
        response = self.post_message("Какие есть ремонтные приборы?")
        self.assertEqual(response.status_code, 201)
        card = response.data.get("faq_card")
        self.assertIsNotNone(card)
        self.assertEqual(card["title"], "Ремонтные приборы")
        self.assertEqual(card["actions"][0]["label"], "Личный кабинет")
        self.assertEqual(card["actions"][0]["href"], faq_service.PERSONAL_CABINET_URL)
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertIn("личный кабинет", bot.get("content", "").casefold())
        self.assertIn("ремонтные приборы", bot.get("content", "").casefold())

    def test_service_center_question_returns_picker(self):
        response = self.post_message("Как найти сервисный центр по промышленному оборудованию в городе №")
        self.assertEqual(response.status_code, 201)
        card = response.data.get("faq_card")
        self.assertIsNotNone(card)
        self.assertEqual(card.get("picker"), "service_center")

    def test_service_centers_catalog_endpoint(self):
        response = self.client.get("/api/service-centers/")
        self.assertEqual(response.status_code, 200)
        categories = response.data.get("categories", {})
        self.assertIn("industrial", categories)
        self.assertIn("grand", categories)
        industrial = categories["industrial"]["countries"][0]["regions"][0]["centers"][0]
        self.assertIn("url", industrial)
        self.assertTrue(industrial["url"].startswith("https://www.turbo-don.ru/diler-card/"))

    def test_button_selection_is_not_intercepted_by_faq(self):
        response = self.post_message(
            "Техническая поддержка",
            hint_state="feedback_pick",
            hint_locked=True,
            is_hint_selection=True,
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data.get("faq_card"))
        self.assertEqual(response.data["hint_state"]["current_state"], "tech_support")
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertIn("по какому оборудованию", bot["content"])

    def test_faq_text_sent_as_hint_selection_does_not_trigger_faq(self):
        response = self.post_message(
            "Техподдержка",
            hint_state="start",
            hint_locked=False,
            is_hint_selection=True,
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data.get("faq_card"))
        self.assertEqual(response.data["hint_state"]["current_state"], "start")
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertNotIn("Макс +7 928 960 92 42", bot["content"])

    def test_uncertain_faq_does_not_return_quick_reply_hints(self):
        response = self.post_message("скачать документ ufg")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["hint_state"]["hints"], [])
        bot = next(msg for msg in response.data["messages"] if not msg["is_user"])
        self.assertIn("напишите: «Консультация»", bot["content"])
        self.assertIn("Где скачать", bot["content"])

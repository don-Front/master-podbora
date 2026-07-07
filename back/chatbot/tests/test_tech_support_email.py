# -*- coding: utf-8 -*-
"""Техподдержка: письмо оператору и учёт в аналитике."""

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient


class TechSupportFeedbackTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        response = self.client.post("/api/chats/", {"title": "Tech support feedback"})
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

    @patch("api.email_service.record_support_request")
    @patch("api.views.EmailSender.send_tech_support_notification")
    def test_tech_support_final_sends_operator_email(self, mock_send, mock_analytics):
        mock_send.return_value = (True, "")

        steps = [
            ("Обратная связь", "start", False, True),
            ("Техническая поддержка", "feedback_pick", True, True),
            ("Бытовые счетчики", "tech_support", True, True),
            ("Гранд 4, ошибка E01", "tech_support_household", True, False),
            ("+7 903 111-22-33 test@example.com", "tech_support_contact", True, False),
        ]

        response = None
        for content, hint_state, hint_locked, is_hint_selection in steps:
            response = self.post_message(
                content,
                hint_state=hint_state,
                hint_locked=hint_locked,
                is_hint_selection=is_hint_selection,
            )
            self.assertEqual(response.status_code, 201, msg=content)

        self.assertEqual(response.data["hint_state"]["current_state"], "tech_support_final")
        self.assertTrue(response.data["email_sent"])
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs["chat_id"], self.chat_id)

    @patch("api.views.EmailSender.send_chat_notification")
    @patch("api.views.EmailSender.send_tech_support_notification")
    def test_order_final_does_not_send_chat_email(self, mock_tech, mock_chat):
        mock_tech.return_value = (True, "")

        self.post_message(
            "Обратная связь",
            hint_state="start",
            hint_locked=False,
            is_hint_selection=True,
        )
        self.post_message(
            "Техническая поддержка",
            hint_state="feedback_pick",
            hint_locked=True,
            is_hint_selection=True,
        )
        self.post_message(
            "Бытовые счетчики",
            hint_state="tech_support",
            hint_locked=True,
            is_hint_selection=True,
        )
        self.post_message(
            "test problem",
            hint_state="tech_support_household",
            hint_locked=True,
            is_hint_selection=False,
        )
        self.post_message(
            "89031112233",
            hint_state="tech_support_contact",
            hint_locked=True,
            is_hint_selection=False,
        )

        mock_chat.assert_not_called()

    @patch("api.email_service.record_support_request")
    def test_analytics_called_after_successful_email(self, mock_analytics):
        mock_analytics.return_value = (True, "")

        from api.email_service import EmailSender

        with patch.object(EmailSender, "_create_smtp_connection") as mock_smtp:
            mock_server = mock_smtp.return_value.__enter__.return_value
            ok, err = EmailSender.send_tech_support_notification(
                messages=[
                    {"is_user": True, "content": "Обратная связь"},
                    {"is_user": True, "content": "Техническая поддержка"},
                    {"is_user": True, "content": "Бытовые счетчики"},
                    {"is_user": True, "content": "Ошибка E01"},
                    {"is_user": True, "content": "+7 903 111-22-33 a@b.ru"},
                ],
                client_email="a@b.ru",
                client_phone="+7 903 111-22-33",
                chat_id=42,
            )

        self.assertTrue(ok)
        mock_analytics.assert_called_once()
        kwargs = mock_analytics.call_args.kwargs
        self.assertEqual(kwargs["email"], "a@b.ru")
        self.assertEqual(kwargs["user_id"], "chat-42")
        self.assertIn("Техническая поддержка", kwargs["topic"])

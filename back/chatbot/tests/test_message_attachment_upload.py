# -*- coding: utf-8 -*-
"""Загрузка PDF/DOCX через multipart не должна падать на request.data.copy()."""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient


def _minimal_pdf_bytes(size: int) -> bytes:
    header = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    if size <= len(header):
        return header
    return header + b"0" * (size - len(header))


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
)
class MessageAttachmentUploadTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        response = self.client.post("/api/chats/", {"title": "Attachment upload"})
        self.assertEqual(response.status_code, 201)
        self.chat_id = response.data["id"]

    def _post_order_pdf_attachment(self, pdf_bytes: bytes, filename: str = "OL_1.pdf"):
        return self.client.post(
            f"/api/chats/{self.chat_id}/messages/",
            {
                "content": "",
                "hint_state": "order_pdf_request",
                "is_hint_selection": "false",
                "hint_locked": "true",
                "attachment": (filename, pdf_bytes, "application/pdf"),
            },
            format="multipart",
        )

    @override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=512)
    def test_temp_file_pdf_multipart_does_not_crash(self) -> None:
        """При FILE_UPLOAD_MAX_MEMORY_SIZE файл уходит во TemporaryUploadedFile."""
        response = self._post_order_pdf_attachment(_minimal_pdf_bytes(2048))
        self.assertEqual(response.status_code, 201, response.content[:500])

    def test_small_pdf_multipart_does_not_crash(self) -> None:
        response = self._post_order_pdf_attachment(_minimal_pdf_bytes(1024))
        self.assertEqual(response.status_code, 201, response.content[:500])

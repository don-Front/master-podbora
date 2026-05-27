from django.test import SimpleTestCase

from api.services import faq_service


class FaqServiceTests(SimpleTestCase):
    def test_exact_excel_question_returns_answer(self):
        result = faq_service.answer("Где скачать Методика поверки UFG")

        self.assertTrue(result.handled)
        self.assertIn("metodika-poverki", result.text)
        self.assertNotIn("Где скачать Методика поверки UFG", result.text)
        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["actions"][0]["type"], "url")
        self.assertIn("Скачать", result.card["actions"][0]["label"])
        self.assertFalse(result.hints)

    def test_rephrased_download_question_matches_faq(self):
        result = faq_service.answer("нужна ссылка на РЭ для расходомера TFG")

        self.assertTrue(result.handled)
        self.assertIn("rje-na-tfg", result.text)

    def test_repair_question_attaches_instruction_pdf(self):
        result = faq_service.answer("как отправить прибор в гарантийный ремонт")

        self.assertTrue(result.handled)
        self.assertIn("Памятка", result.text)
        self.assertEqual(result.card["actions"][0]["type"], "file")
        self.assertIsNotNone(result.attachment_path)
        self.assertTrue(result.attachment_path.is_file())
        self.assertIn("Памятка", result.attachment_name)

    def test_support_answer_has_clickable_phone_card(self):
        result = faq_service.answer("контакты техподдержки")

        self.assertTrue(result.handled)
        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["title"], "Техническая поддержка")
        self.assertEqual(result.card["actions"][0]["type"], "phone")
        self.assertTrue(result.card["actions"][0]["href"].startswith("tel:"))

    def test_official_letter_has_clickable_email_card(self):
        result = faq_service.answer("как написать официальное письмо")

        self.assertTrue(result.handled)
        self.assertEqual(result.card["actions"][0]["type"], "email")
        self.assertEqual(result.card["actions"][0]["href"], "mailto:info@turbo-don.ru")

    def test_uncertain_faq_intent_returns_two_hints(self):
        result = faq_service.answer("скачать документ ufg")

        self.assertTrue(result.handled)
        self.assertEqual(result.hints[0], faq_service.CONSULTATION_HINT)
        self.assertTrue(result.hints[1].startswith("Где скачать"))

    def test_product_characteristics_question_goes_to_rag(self):
        result = faq_service.answer("какая погрешность у расходомера UFG-H?")

        self.assertFalse(result.handled)
        self.assertTrue(result.needs_rag)

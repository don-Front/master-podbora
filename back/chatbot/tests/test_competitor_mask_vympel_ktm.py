"""Тесты расшифровки масок Вымпел-500 и КТМ600 РУС."""

from __future__ import annotations

from django.test import SimpleTestCase

from api.competitor_masks import competitor_mask_decoder
from api.competitor_masks.service import format_decode_response


class Vympel500MaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "Вымпел-500-500-И6-0,5-1-4К-01-ТП200-ИБП-БИ-С-G"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["dn"], "500")
        self.assertEqual(values["pressure"], "И6")
        self.assertEqual(values["accuracy"], "0.5")
        self.assertEqual(values["channels"], "4К")
        self.assertEqual(values["power_type"], "С")

    def test_invalid_channels(self) -> None:
        mask = "Вымпел-500-200-И16-0,5-1-3К-01-С"
        result = competitor_mask_decoder.decode(mask)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field_id, "channels")
        self.assertIn("4К", result.errors[0].allowed)


class Ktm600MaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "КТМ600 РУС 2P01DN100PN0160L0300GB1N-М1-DC5"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["layout"], "2P")
        self.assertEqual(values["material"], "01")
        self.assertEqual(values["dn"], "DN100")
        self.assertEqual(values["pn"], "PN0160")
        self.assertEqual(values["length"], "L0300")
        self.assertEqual(values["io"], "DC5")

    def test_invalid_pn(self) -> None:
        mask = "КТМ600 РУС 2P01DN100PN0120L0300GB1N-DC5"
        result = competitor_mask_decoder.decode(mask)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field_id, "pn")
        text = format_decode_response(result)
        self.assertIn("PN0160", text)

    def test_detection(self) -> None:
        self.assertTrue(competitor_mask_decoder.looks_like_mask("КТМ600 РУС 2P01DN100PN0160L0300GB1N-DC5"))
        self.assertTrue(competitor_mask_decoder.looks_like_mask("Вымпел-500-500-И6-0,5-1-4К-01-С"))

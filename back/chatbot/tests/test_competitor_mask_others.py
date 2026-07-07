"""Тесты расшифровки масок РСГ СИГНАЛ, ИРВИС-Ультра, ULTRAMAG."""

from __future__ import annotations

from django.test import SimpleTestCase

from api.competitor_masks import competitor_mask_decoder
from api.competitor_masks.service import format_decode_response


class RsgSignalMaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        result = competitor_mask_decoder.decode("РСГ СИГНАЛ-40-G10-1-PN16-B")
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(
            values,
            {
                "dn": "DN40",
                "size": "G10",
                "accuracy_variant": "1",
                "pn": "PN16",
                "body": "B",
            },
        )

    def test_invalid_size(self) -> None:
        result = competitor_mask_decoder.decode("РСГ СИГНАЛ-40-G12-1-PN16-B")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field_id, "size")
        self.assertIn("G10", result.errors[0].allowed)


class IrvisUltraMaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        result = competitor_mask_decoder.decode("ИРВИС-Ультра-Пп-16-DN200-100-ГОТ")
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(
            values,
            {
                "pressure": "16",
                "dn": "DN200",
                "qmax": "100",
                "accuracy": "ГОТ",
            },
        )

    def test_invalid_dn(self) -> None:
        result = competitor_mask_decoder.decode("ИРВИС-Ультра-Пп-16-DN250-100-ГОТ")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field_id, "dn")
        self.assertIn("DN200", result.errors[0].allowed)

    def test_invalid_pressure(self) -> None:
        result = competitor_mask_decoder.decode("ИРВИС-Ультра-Пп-12-DN200-100-ГОТ")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field_id, "pressure")
        self.assertEqual(result.errors[0].raw_value, "12")
        self.assertIn("16", result.errors[0].allowed)
        text = format_decode_response(result)
        self.assertIn("12", text)
        self.assertIn("нет в РЭ", text)


class UltramagMaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "ULTRAMAG-Б-А-PTZ-50-G25-1:160-1-1А-П-R"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["ivb"], "Б")
        self.assertEqual(values["layout"], "А")
        self.assertEqual(values["channels"], "PTZ")
        self.assertEqual(values["dn"], "50")
        self.assertEqual(values["size"], "G25")
        self.assertEqual(values["dynamic_range"], "1:160")
        self.assertEqual(values["accuracy"], "1")
        self.assertEqual(values["direction"], "П")
        self.assertEqual(values["reversible"], "R")

    def test_invalid_dynamic_range(self) -> None:
        mask = "ULTRAMAG-Б-А-PTZ-50-G25-1:999-1-1А-П"
        result = competitor_mask_decoder.decode(mask)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors[0].field_id, "dynamic_range")
        text = format_decode_response(result)
        self.assertIn("1:160", text)

    def test_detection_priority_ultramag(self) -> None:
        self.assertTrue(competitor_mask_decoder.looks_like_mask("ULTRAMAG-Б-А-PTZ-50-G25-1:160-1-1А-П"))

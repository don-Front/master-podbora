"""Тесты расшифровки масок новых конкурентов (KTM700, KTM РуМАСС, ЭЛМЕТРО, ЭМИС)."""

from __future__ import annotations

from django.test import SimpleTestCase

from api.competitor_masks import competitor_mask_decoder
from api.competitor_masks.analog_mapper import build_analog_search_specs


class Ktm700MaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "КТМ700 РУС 2P01DN0050PN0160GB1N20NL3N01AC1"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["layout"], "2P")
        self.assertEqual(values["dn"], "DN0050")
        self.assertEqual(values["pn"], "PN0160")
        self.assertEqual(values["boi"], "L3")
        self.assertEqual(values["temp"], "C1")

    def test_invalid_layout(self) -> None:
        mask = "КТМ700 РУС 3P01DN0050PN0160GB1N20NL3N01AC1"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertFalse(result.parsed_fields)


class KtmRumassMaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "КТМ РуМАСС050-0-0-386-00-25-1-1"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["dn"], "050")
        self.assertEqual(values["accuracy"], "25")
        self.assertEqual(values["remote"], "1")


class ElmetroFlomakMaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "ЭЛМЕТРО-Фломак-ExB-S025-LEU-301-RS-LUM-C-G-CZX-IXX"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["ex_protection"], "ExB")
        self.assertEqual(values["sensor_type"], "S")
        self.assertEqual(values["dn"], "025")
        self.assertEqual(values["pressure"], "L")
        self.assertEqual(values["accuracy"], "E")


class ElmetroFlousDruMaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "ЭЛМЕТРО-Флоус.1-Ex-C050-CI-BN-XXXS-015-OM-AC-G-CZX-XX"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["channels"], "1")
        self.assertEqual(values["body"], "C")
        self.assertEqual(values["dn"], "050")
        self.assertEqual(values["accuracy"], "C")
        self.assertEqual(values["function"], "I")
        self.assertEqual(values["pressure"], "B")


class EmisMass260MaskTests(SimpleTestCase):
    def test_valid_mask(self) -> None:
        mask = "ЭМИС-МАСС-260 – Ex – 050К – И – Ж – 2,5 – 100 – 24 – А1 – 0,25 – 1,0 – 1,0 – НК – У – ГП – Е – ГОСТ"
        result = competitor_mask_decoder.decode(mask)
        self.assertTrue(result.handled)
        self.assertTrue(result.is_valid)
        values = {field.field_id: field.value for field in result.parsed_fields}
        self.assertEqual(values["ex_protection"], "Ex")
        self.assertEqual(values["dn"], "050")
        self.assertEqual(values["body"], "К")
        self.assertEqual(values["placement"], "И")
        self.assertEqual(values["calibration"], "Ж")
        self.assertEqual(values["pressure"], "2,5")
        self.assertEqual(values["accuracy"], "0,25")


class NewCompetitorAnalogMapperTests(SimpleTestCase):
    def test_ktm_700_analog_specs(self) -> None:
        result = competitor_mask_decoder.decode("КТМ700 РУС 2P01DN0050PN0160GB1N20NL3N01AC1")
        analog = build_analog_search_specs(result.catalog_id, result.parsed_fields, is_valid=result.is_valid)
        self.assertIsNotNone(analog.specs)
        self.assertEqual(analog.specs.get("diameter"), 50)
        self.assertEqual(analog.specs.get("pressureMax"), 16.0)

    def test_elmetro_flous_analog_specs(self) -> None:
        result = competitor_mask_decoder.decode("ЭЛМЕТРО-Флоус.1-Ex-C050-CI-BN-XXXS-015-OM-AC-G-CZX-XX")
        analog = build_analog_search_specs(result.catalog_id, result.parsed_fields, is_valid=result.is_valid)
        self.assertIsNotNone(analog.specs)
        self.assertEqual(analog.specs.get("diameter"), 50)
        self.assertEqual(analog.specs.get("pressureMax"), 2.5)
        self.assertEqual(analog.specs.get("accuracy"), "1.0")


class NewCompetitorDetectionTests(SimpleTestCase):
    def test_detection_priority(self) -> None:
        self.assertTrue(competitor_mask_decoder.looks_like_mask("КТМ700 РУС 2P01DN0050PN0160GB1N20NL3N01AC1"))
        self.assertTrue(competitor_mask_decoder.looks_like_mask("КТМ РуМАСС050-0-0-386-00-25-1-1"))
        self.assertTrue(competitor_mask_decoder.looks_like_mask("ЭЛМЕТРО-Фломак-ExB-S025-LEU-301-RS-LUM-C-G-CZX-IXX"))
        self.assertTrue(competitor_mask_decoder.looks_like_mask("ЭЛМЕТРО-Флоус.1-Ex-C050-CI-BN-XXXS-015-OM-AC-G-CZX-XX"))
        self.assertTrue(competitor_mask_decoder.looks_like_mask("ЭМИС-МАСС-260 – Ex – 050К – И – Ж – 2,5 – 100 – 24 – А1 – 0,25"))

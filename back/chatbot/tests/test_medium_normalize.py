# -*- coding: utf-8 -*-

from django.test import SimpleTestCase

from api.medium_normalize import (
    MEDIUM_UNSUPPORTED_MESSAGE,
    normalize_medium_from_user_text,
    try_normalize_medium_value,
)
from api.order_specs_helpers import FIELD_PROMPTS, parse_field_value


class MediumNormalizeTests(SimpleTestCase):
    def test_gas_variants(self) -> None:
        for text in (
            "gas",
            "газ",
            "природный газ",
            "сжиженный газ",
            "попутный газ",
            "азот",
            "воздух",
            "natural gas",
        ):
            with self.subTest(text=text):
                self.assertEqual(normalize_medium_from_user_text(text), "gas")

    def test_liquid_variants(self) -> None:
        for text in ("liquid", "жидкость", "нефть", "вода", "масло"):
            with self.subTest(text=text):
                self.assertEqual(normalize_medium_from_user_text(text), "liquid")

    def test_unsupported_medium(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            normalize_medium_from_user_text("пар")
        self.assertEqual(str(ctx.exception), MEDIUM_UNSUPPORTED_MESSAGE)

    def test_parse_field_value_medium(self) -> None:
        self.assertEqual(parse_field_value("medium", "природный газ"), "gas")
        self.assertEqual(parse_field_value("medium", "нефть"), "liquid")

    def test_soft_normalize_keeps_unknown_llm_value(self) -> None:
        self.assertEqual(try_normalize_medium_value("unknown"), "unknown")
        self.assertEqual(try_normalize_medium_value("пар"), "пар")

    def test_medium_prompt_is_short(self) -> None:
        self.assertEqual(
            FIELD_PROMPTS["medium"],
            "Укажите среду измерения (газ или жидкость).",
        )

"""Юнит-тесты детектора интента подбора оборудования по свободному тексту."""

from django.test import SimpleTestCase

from api.order_specs_helpers import (
    build_order_specs_review_rows,
    list_missing_fields,
    merge_draft,
    parse_field_value,
)
from api.order_specs_text import looks_like_order_specs_request
from api.pdf_order_analysis import extract_specs_heuristic


class OrderSpecsIntentTest(SimpleTestCase):
    def test_no_selection_keyword_goes_to_rag(self):
        msg = (
            "Нужен расходомер для учета сжиженного газа на заправке с низкой вязкостью. "
            "Какие параметры нужно уточнить?"
        )
        self.assertFalse(looks_like_order_specs_request(msg))

    def test_selection_keyword_triggers_flow(self):
        self.assertTrue(
            looks_like_order_specs_request("Подберите расходомер для учета сжиженного газа на заправке")
        )
        self.assertTrue(
            looks_like_order_specs_request("Нужен подбор расходомера DN50, газ, 1.6 МПа")
        )
        self.assertTrue(
            looks_like_order_specs_request("Помогите подобрать оборудование для измерения расхода газа")
        )

    def test_short_or_empty(self):
        self.assertFalse(looks_like_order_specs_request("подбор"))
        self.assertFalse(looks_like_order_specs_request(""))


class OrderSpecsOptionalFieldsTest(SimpleTestCase):
    def test_gas_type_is_optional_for_selection(self):
        draft = {
            "medium": "gas",
            "gas_type": None,
            "flowMin": 10,
            "flowMax": 500,
            "flow_unit": "ст.м³/ч",
            "pressureMin": 0.1,
            "pressureMax": 1.6,
            "pressure_unit": "МПа",
            "tempMediumMin": -10,
            "tempMediumMax": 30,
            "tempAmbientMin": -40,
            "tempAmbientMax": 40,
            "temperature_unit": "°C",
            "accuracy": "1%",
            "diameter": 100,
        }

        self.assertNotIn("gas_type", list_missing_fields(draft))

        gas_type_row = next(
            row for row in build_order_specs_review_rows(draft) if row["key"] == "gas_type"
        )
        self.assertEqual(gas_type_row["label"], "Тип газа (необязательно)")
        self.assertEqual(gas_type_row["value"], "")

    def test_gas_duplication_defaults_to_none_and_is_visible(self):
        draft = merge_draft(
            {
                "medium": "gas",
                "flowMin": 10,
                "flowMax": 500,
                "flow_unit": "ст.м³/ч",
                "pressureMin": 0.1,
                "pressureMax": 1.6,
                "pressure_unit": "МПа",
                "accuracy": "1%",
                "diameter": 100,
            }
        )

        self.assertEqual(draft["duplication_type"], "none")
        self.assertNotIn("duplication_type", list_missing_fields(draft))

        row = next(
            row for row in build_order_specs_review_rows(draft) if row["key"] == "duplication_type"
        )
        self.assertEqual(row["value"], "без дублирования")

    def test_duplication_is_hidden_for_liquid(self):
        draft = merge_draft({"medium": "liquid", "duplication_type": "full"})
        self.assertIsNone(draft["duplication_type"])
        self.assertNotIn("duplication_type", list_missing_fields(draft))
        self.assertFalse(
            any(row["key"] == "duplication_type" for row in build_order_specs_review_rows(draft))
        )

    def test_gas_type_is_hidden_for_liquid(self):
        draft = merge_draft({"medium": "liquid", "gas_type": "Пресная вода"})
        self.assertFalse(
            any(row["key"] == "gas_type" for row in build_order_specs_review_rows(draft))
        )

    def test_duplication_is_not_requested_before_gas_medium(self):
        self.assertNotIn("duplication_type", list_missing_fields({"medium": None}))
        self.assertNotIn("duplication_type", list_missing_fields({"medium": "liquid"}))

    def test_duplication_manual_input_validation(self):
        self.assertEqual(parse_field_value("duplication_type", "частичное дублирование"), "partial")
        self.assertEqual(parse_field_value("duplication_type", "полное резервирование"), "full")
        with self.assertRaises(ValueError):
            parse_field_value("duplication_type", "двойное")


class OrderSpecsTemperatureDefaultsTest(SimpleTestCase):
    def test_gas_missing_temperatures_are_filled(self):
        draft = {
            "medium": "gas",
            "flowMin": 10,
            "flowMax": 500,
            "flow_unit": "ст.м³/ч",
            "pressureMin": 0.1,
            "pressureMax": 1.6,
            "pressure_unit": "МПа",
            "accuracy": "1%",
            "diameter": 100,
        }
        missing = list_missing_fields(draft)
        self.assertNotIn("tempMediumMin", missing)
        self.assertNotIn("tempMediumMax", missing)
        self.assertNotIn("tempAmbientMin", missing)
        self.assertNotIn("tempAmbientMax", missing)
        self.assertNotIn("temperature_unit", missing)

    def test_liquid_default_working_medium_max_is_60(self):
        from api.order_specs_helpers import merge_draft

        draft = merge_draft({"medium": "liquid", "flowMin": 1, "flowMax": 10})
        self.assertEqual(draft["tempMediumMax"], 60)
        self.assertEqual(draft["tempAmbientMax"], 70)

    def test_recognized_temperatures_are_not_overwritten(self):
        from api.order_specs_helpers import merge_draft

        draft = merge_draft(
            {
                "medium": "gas",
                "tempMediumMin": -10,
                "tempMediumMax": 40,
                "tempAmbientMin": -20,
                "tempAmbientMax": 50,
                "temperature_unit": "°C",
            }
        )
        self.assertEqual(draft["tempMediumMin"], -10)
        self.assertEqual(draft["tempMediumMax"], 40)
        self.assertEqual(draft["tempAmbientMin"], -20)
        self.assertEqual(draft["tempAmbientMax"], 50)


class OrderSpecsMeasurementUnitDefaultsTest(SimpleTestCase):
    def test_missing_flow_and_pressure_units_are_filled(self):
        from api.order_specs_helpers import merge_draft, list_missing_fields

        draft = merge_draft(
            {
                "medium": "gas",
                "flowMin": 10,
                "flowMax": 500,
                "pressureMin": 0.1,
                "pressureMax": 1.6,
                "accuracy": "1%",
                "diameter": 100,
            }
        )
        self.assertEqual(draft["flow_unit"], "м³/ч")
        self.assertEqual(draft["pressure_unit"], "МПа")
        self.assertNotIn("flow_unit", list_missing_fields(draft))
        self.assertNotIn("pressure_unit", list_missing_fields(draft))


class OrderSpecsPdfHeuristicTest(SimpleTestCase):
    def test_gazprom_questionnaire_table_and_appendix_are_extracted(self):
        text = """
        12 Характеристика среды: Другие ед.
        измерения Min Nom Max
        12.1 Расход объемный, м3/ч при
        стандартных условиях. 100 40000
        12.2 Давление, МПа,
        (подчеркнуть: изб./абс). 0,6 1,2
        12.3 Температура, 0С. 0 30
        15.6 Предел допускаемой относительной погрешности измерения.
        классу В с пределом допускаемой относительной погрешности ± 1,5 %.
        17.2 Количество по спецификации
        1 комплект из двух ИТ DN300 и линии малого расхода DN50

        Приложение А. Характеристики рабочей среды
        Температура окружающего воздуха, ºС:
        - абсолютная минимальная
        - абсолютная максимальная
        Минус 33
        Плюс 42
        """

        specs = extract_specs_heuristic(text)

        self.assertEqual(specs["flowMin"], 100)
        self.assertEqual(specs["flowMax"], 40000)
        self.assertEqual(specs["flow_unit"], "ст.м³/ч")
        self.assertEqual(specs["pressureMin"], 0.6)
        self.assertEqual(specs["pressureMax"], 1.2)
        self.assertEqual(specs["tempMediumMin"], 0)
        self.assertEqual(specs["tempMediumMax"], 30)
        self.assertEqual(specs["tempAmbientMin"], -33)
        self.assertEqual(specs["tempAmbientMax"], 42)
        self.assertEqual(specs["accuracy"], "1.5%")
        self.assertEqual(specs["diameter"], 300)

    def test_recognized_units_are_not_overwritten(self):
        from api.order_specs_helpers import merge_draft

        draft = merge_draft(
            {
                "flowMin": 1,
                "flowMax": 2,
                "flow_unit": "нм³/ч",
                "pressureMax": 10,
                "pressure_unit": "бар",
            }
        )
        self.assertEqual(draft["flow_unit"], "нм³/ч")
        self.assertEqual(draft["pressure_unit"], "бар")


class OrderSpecsPhase1HeuristicTest(SimpleTestCase):
    def test_z958957_composition_and_qmax_flow(self):
        text = """
        DN150 DN50
        CH4  98,86 C2H6  0,100 C3H8  0,009 CO2  0,100 N2  0,880 Ar  0,033
        Qmin ,01Qmax 0,5 0,3 0,01Qmax Qmax 0,5 0,3
        0.5%-0.3%
        """
        specs = extract_specs_heuristic(text)
        self.assertEqual(specs["medium"], "gas")
        self.assertIn("CH4", specs["gas_type"])
        self.assertEqual(specs["flowMin"], 0.01)
        self.assertEqual(specs["flowMax"], 0.5)
        self.assertEqual(specs["flow_unit"], "Qmax")
        self.assertEqual(specs["accuracy"], "0.5%-0.3%")

    def test_ot_do_flow_and_pressure_ranges(self):
        text = """
        Расход нм³/ч от 5500 до 35000
        Рабочее давление на входе МПа От 3.4 до 5.4
        """
        specs = extract_specs_heuristic(text)
        self.assertEqual(specs["flowMin"], 5500)
        self.assertEqual(specs["flowMax"], 35000)
        self.assertEqual(specs["pressureMin"], 3.4)
        self.assertEqual(specs["pressureMax"], 5.4)

    def test_gazprom_table_detects_kpa(self):
        text = """
        12.2 Давление, кПа (изб./абс). 60 100
        """
        from api.pdf_order_analysis import _extract_gazprom_table_12_specs

        specs = _extract_gazprom_table_12_specs(text)
        self.assertEqual(specs["pressure_unit"], "кПа")
        self.assertEqual(specs["pressureMin"], 60)
        self.assertEqual(specs["pressureMax"], 100)

    def test_duplication_partial_from_two_meters_kit(self):
        text = "1 комплект из двух ИТ DN300 и линии малого расхода DN50"
        from api.pdf_order_analysis import extract_duplication_type_from_text

        self.assertEqual(extract_duplication_type_from_text(text), "partial")

    def test_accuracy_bare_decimal_without_percent(self):
        from api.pdf_order_analysis import normalize_accuracy_value

        self.assertEqual(normalize_accuracy_value("0,5"), "0,5")
        self.assertEqual(normalize_accuracy_value("0.5%"), "0.5%")
        self.assertEqual(normalize_accuracy_value("0.5%-0.3%"), "0.5%-0.3%")

    def test_dn_ocr_token_decodes_dn100(self):
        from api.pdf_order_analysis import _decode_dn_ocr_token, _extract_nominal_diameter

        self.assertEqual(_decode_dn_ocr_token("10OD"), 100)
        self.assertEqual(_decode_dn_ocr_token("1O0"), 100)
        text = "Типоразмер DN10OD и запасной DN 50"
        self.assertEqual(_extract_nominal_diameter(text), 100)

    def test_tfg_flow_scale_correction(self):
        from api.pdf_order_analysis import _correct_flow_max_outlier

        specs = {"flowMin": 20.99, "flowMax": 12593.08, "flow_unit": "ст.м³/ч"}
        fixed = _correct_flow_max_outlier(
            specs,
            "Диапазон расхода стандарт нм³/ч Qmax 12 Qmin 20.99",
        )
        self.assertEqual(fixed["flowMax"], 12)
        self.assertEqual(fixed["flow_unit"], "нм³/ч")

    def test_turbo_branded_ufl_sets_liquid_and_clears_dup(self):
        from api.pdf_order_analysis import _extract_turbo_branded_specs

        text = (
            "Опросный лист расходомера UFL №1\n"
            "Количество приборов\n2\n"
            "Диаметр условного прохода Dn: 500\n"
            "Pmax расчетное, МПа: 10\n"
            "Класс точности прибора: 1% (Б)\n"
            "Количество лучей: 8\n"
            "Т окружающего воздуха, °С: -48 - 27\n"
        )
        specs = _extract_turbo_branded_specs(text)
        self.assertEqual(specs["medium"], "liquid")
        self.assertIsNone(specs["duplication_type"])
        self.assertEqual(specs["diameter"], 500)
        self.assertEqual(specs["tempAmbientMin"], -48)
        self.assertEqual(specs["tempAmbientMax"], 27)

    def test_sanitize_suspicious_flow_removes_ray_counts(self):
        from api.pdf_order_analysis import _sanitize_suspicious_flow

        specs = {"flowMin": 2, "flowMax": 4, "flow_unit": "нм³/ч"}
        cleaned = _sanitize_suspicious_flow(specs, "Количество лучей: 4\nДиаметр Dn: 500")
        self.assertIsNone(cleaned["flowMin"])
        self.assertIsNone(cleaned["flowMax"])

    def test_sanitize_pressure_pn_rating(self):
        from api.pdf_order_analysis import _sanitize_pressure_pn_rating

        specs = {"pressureMin": 16, "pressureMax": 16, "pressure_unit": "МПа"}
        cleaned = _sanitize_pressure_pn_rating(specs, "Давление фланцев PN16\nРабочее давление 0-6 МПа")
        self.assertIsNone(cleaned["pressureMin"])
        self.assertIsNone(cleaned["pressureMax"])

    def test_gazprom_ufg_scan_extracts_dn_and_pressure(self):
        from api.pdf_order_analysis import _extract_gazprom_ufg_scan_ol

        text = (
            "Ультразвуковой расходомер TurboFlowUFG\n"
            "Дняметр условного\n250\n"
            "Давление рабочее 0 - 6 МПа\n"
            "Класс тпчности прибора 1\n"
        )
        specs = _extract_gazprom_ufg_scan_ol(text)
        self.assertEqual(specs["diameter"], 250)
        self.assertEqual(specs["pressureMin"], 0)
        self.assertEqual(specs["pressureMax"], 6)
        self.assertIn("класс точности", specs["accuracy"])

    def test_prefer_heuristic_keeps_large_llm_flows(self):
        from api.pdf_order_analysis import _prefer_consistent_heuristic_ranges

        llm_specs = {"flowMin": 44.5, "flowMax": 14241.6, "flow_unit": "нм³/ч"}
        heuristic = {"flowMin": 2, "flowMax": 4, "flow_unit": "нм³/ч"}
        out = _prefer_consistent_heuristic_ranges(
            llm_specs,
            heuristic,
            "Диапазон расхода Qmin 44.5 Qmax 14241.6 Количество лучей: 8",
        )
        self.assertEqual(out["flowMin"], 44.5)
        self.assertEqual(out["flowMax"], 14241.6)

    def test_validate_keeps_percent_accuracy(self):
        from api.pdf_order_analysis import _validate_and_sanitize_specs

        specs = {"accuracy": "0.5%", "medium": "gas"}
        text = "Класстылевпаазащиь 12 4 НАНТ точности прибора"
        out = _validate_and_sanitize_specs(specs, text)
        self.assertEqual(out["accuracy"], "0.5%")

    def test_gazprom_fuzzy_pressure_ocr(self):
        from api.pdf_order_analysis import _extract_gazprom_ufg_scan_ol

        text = (
            "Ультразвуковой расходомер TurboFlowUFG\n"
            "Дняметр 250\n"
            "Плсчёт МПlа 0 - 6\n"
            "Класс тпчности приборu\n"
        )
        specs = _extract_gazprom_ufg_scan_ol(text)
        self.assertEqual(specs.get("pressureMin"), 0)
        self.assertEqual(specs.get("pressureMax"), 6)

    def test_turbo_branded_ufl_temp_medium(self):
        from api.pdf_order_analysis import _extract_turbo_branded_specs

        text = (
            "Опросный лист расходомера UFL №1\n"
            "Температура рабочей среды, °С: -50 - 70\n"
            "Давление измеряемой среды 5 - 9,34 МПа\n"
        )
        specs = _extract_turbo_branded_specs(text)
        self.assertEqual(specs["tempMediumMin"], -50)
        self.assertEqual(specs["tempMediumMax"], 70)
        self.assertEqual(specs["pressureMin"], 5)
        self.assertEqual(specs["pressureMax"], 9.34)

    def test_gazprom_fuzzy_pressure_after_class_block(self):
        from api.pdf_order_analysis import _extract_gazprom_ufg_scan_ol

        text = (
            "Ультразвуковой расходомер TurboFlowUFG\n"
            "Дняметр 250\n"
            "Класс тпчности\n"
            "пpиuорu\n"
            "От Оnn Ло {NQ\n"
            "ОтООIОных Ла Опu\n"
        )
        specs = _extract_gazprom_ufg_scan_ol(text)
        self.assertEqual(specs.get("pressureMin"), 0)
        self.assertEqual(specs.get("pressureMax"), 6)

    def test_validate_keeps_ufl_turbo_accuracy(self):
        from api.pdf_order_analysis import _validate_and_sanitize_specs

        text = (
            "Опросный лист расходомера UFL №1\n"
            "Класс точности прибора: 1% (Б)\n"
            "Количество лучей: 8\n"
        )
        specs = {"accuracy": "1%", "medium": "liquid", "diameter": 500}
        out = _validate_and_sanitize_specs(specs, text)
        self.assertEqual(out["accuracy"], "1%")

    def test_correct_flow_max_keeps_ufl_engineering_flows(self):
        from api.pdf_order_analysis import _correct_flow_max_outlier

        text = (
            "Опросный лист расходомера UFL №1\n"
            "Диапазон расхода Qmin 44.505 Qmax 14241.6 нм³/ч\n"
        )
        specs = {"flowMin": 44.505, "flowMax": 14241.6, "flow_unit": "нм³/ч"}
        out = _correct_flow_max_outlier(specs, text)
        self.assertEqual(out["flowMax"], 14241.6)

    def test_tfg_poverka_gaz_does_not_force_medium_gas(self):
        from api.pdf_order_analysis import _extract_turbo_branded_specs, _validate_and_sanitize_specs

        text = (
            "Опросный лист расходомера TFG №1\n"
            "Pmax расчетное, МПа: 1,6\n"
            "Поверка\n"
            "Газ\n"
            "Класс точности прибора: 2.5% - 1.5%\n"
        )
        turbo = _extract_turbo_branded_specs(text)
        self.assertNotIn("medium", turbo)
        specs = _validate_and_sanitize_specs(
            {"medium": "Попутный нефтяной (сырой) газ", "gas_type": "попутный нефтяной газ"},
            text,
        )
        self.assertEqual(specs["medium"], "liquid")
        self.assertIn("газ", specs["gas_type"].casefold())

    def test_tfg_low_working_pressure_range(self):
        from api.pdf_order_analysis import _extract_turbo_branded_specs

        text = (
            "Опросный лист расходомера TFG №1\n"
            "Pmax расчетное, МПа: 1,6\n"
            "Давление измеряемой среды 0,001 - 0,015 МПа\n"
        )
        specs = _extract_turbo_branded_specs(text)
        self.assertEqual(specs["pressureMin"], 0.001)
        self.assertEqual(specs["pressureMax"], 0.015)

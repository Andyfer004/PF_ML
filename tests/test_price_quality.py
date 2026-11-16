import unittest
from datetime import date
from decimal import Decimal

from src.price_quality import identify_panel_fuels,labelled_prices, normalize_fuel, parse_price, quarantine_review_flags, transaction_unit_price, validate_candidate, week_start


def line(text, x, y, confidence=0.99):
    return {"texto": text, "confianza": confidence,
            "bbox": [[x-10, y-5], [x+10, y-5], [x+10, y+5], [x-10, y+5]]}


class PriceQualityTests(unittest.TestCase):
    def test_review_flag_excludes_uncertain_ocr_without_inventing_a_replacement(self):
        original=[{"foto_origen":"photo","combustible":"super","precio_q_galon":"36.79","estado":"candidato"},
                  {"foto_origen":"photo","combustible":"regular","precio_q_galon":"34.89","estado":"candidato"}]
        result=quarantine_review_flags(original,{("photo","super"):"DUDOSA"})
        self.assertIsNone(result[0]["precio_q_galon"])
        self.assertEqual(result[0]["precio_sin_validar"],"36.79")
        self.assertEqual(result[1]["precio_q_galon"],"34.89")
        self.assertEqual(original[0]["precio_q_galon"],"36.79")
    def test_transaction_checks_unit_price_without_guessing_which_fuel_was_bought(self):
        lines=[line("150.00",300,100),line("4.660",300,200)]
        self.assertEqual(transaction_unit_price(lines,1000),Decimal("32.19"))
        self.assertIsNone(transaction_unit_price(lines+[line("200.00",300,120)],1000))
    def test_reversed_pump_labels_determine_fuel_identity(self):
        regions=[{"bbox":[[x-30,600],[x+30,600],[x+30,650],[x-30,650]]} for x in (100,200,300,400)]
        lines=[line(text,x,760) for text,x in (("V-Power",100),("Super",200),("Regular",300),("Diesel",400))]
        self.assertEqual(identify_panel_fuels(regions,lines,1000),{0:"vpower",1:"super",2:"regular",3:"diesel"})

    def test_hidden_label_needs_three_other_shell_labels(self):
        regions=[{"bbox":[[x-30,600],[x+30,600],[x+30,650],[x-30,650]]} for x in (100,200,300,400)]
        lines=[line(text,x,760) for text,x in (("Regular",200),("Super",300),("V-Power",400))]
        self.assertNotIn(0,identify_panel_fuels(regions,lines,1000))
        self.assertEqual(identify_panel_fuels(regions,lines+[line("Shell",200,700)],1000)[0],"diesel")

    def test_does_not_invent_missing_decimal_or_reverse_digits(self):
        for text in ("6926", "6ELE", "10.208", "150.00 galones"):
            self.assertIsNone(parse_price(text))
        self.assertEqual(parse_price("Q 39,39"), Decimal("39.39"))

    def test_labels_with_accents_and_ambiguous_labels(self):
        self.assertEqual(normalize_fuel("Diésel"), "diesel")
        self.assertIsNone(normalize_fuel("regular super"))

    def test_sale_total_and_gallons_are_not_matched_to_fuel(self):
        lines = [line("150.00", 300, 80), line("3.938", 300, 150),
                 line("39.39", 300, 650), line("Diésel", 300, 800)]
        self.assertEqual(labelled_prices(lines, 1000, 1000)["diesel"]["precio"], "39.39")

    def test_multiple_prices_for_one_label_are_ambiguous(self):
        lines = [line("39.39", 300, 650), line("38.39", 300, 660), line("Diésel", 300, 800)]
        self.assertNotIn("diesel", labelled_prices(lines, 1000, 1000))

    def test_confident_but_different_predictions_are_rejected(self):
        readings = [{"precio": "32.19", "confianza": 0.99},
                    {"precio": "32.79", "confianza": 0.99}]
        self.assertIn("VISTAS_DISCREPAN", validate_candidate("super", date(2026, 11, 8), readings))

    def test_quality_accumulates_missing_and_future_data(self):
        self.assertIn("LECTURAS_INSUFICIENTES", validate_candidate("diesel", None, []))
        reasons = validate_candidate("invalid", date(2026, 12, 1),
                                     [{"precio": "999", "confianza": 0.5}], today=date(2026, 11, 16))
        for reason in ("COMBUSTIBLE_INVALIDO", "FECHA_FUTURA", "PRECIO_FUERA_RANGO", "CONFIANZA_BAJA"):
            self.assertIn(reason, reasons)

    def test_tuesday_to_monday_boundary(self):
        self.assertEqual(week_start(date(2026, 7, 13)), date(2026, 7, 7))
        self.assertEqual(week_start(date(2026, 7, 14)), date(2026, 7, 14))


if __name__ == "__main__":
    unittest.main()

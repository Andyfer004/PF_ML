import unittest

from scripts.evaluate_ocr import evaluate


class EvaluationTests(unittest.TestCase):
    def test_missing_prices_reduce_accuracy_even_when_every_returned_price_is_correct(self):
        report = {"resultados": [
            {"foto_origen": "s3://photos/photo.HEIC", "combustible": "super", "precio_q_galon": "38.09"},
            {"foto_origen": "s3://photos/photo.HEIC", "combustible": "diesel", "precio_q_galon": None},
            {"foto_origen": "s3://photos/photo.HEIC", "combustible": "regular", "precio_q_galon": None},
        ]}
        refs = [{"archivo": "photo.HEIC", "precio_super": "38.09", "precio_regular": "37.09", "precio_diesel": "39.39"}]
        result = evaluate(report, refs)
        self.assertEqual(result["exactitud_incluyendo_omisiones"], 1 / 3)
        self.assertEqual(result["precision_sobre_extraidos"], 1)
        self.assertFalse(result["cumple_minimo_20_fotos"])

    def test_unreviewed_template_is_not_ground_truth(self):
        report = {"resultados": [{"foto_origen": "photo.HEIC", "combustible": "super", "precio_q_galon": "38.09"}]}
        refs = [{"foto_origen": "photo.HEIC", "precio_super_manual": "38.09", "revisor": ""}]
        self.assertIsNone(evaluate(report, refs)["exactitud_incluyendo_omisiones"])

    def test_uncertain_user_reading_is_not_a_confirmed_human_reference(self):
        report={"resultados":[{"foto_origen":"photo.HEIC","combustible":"super","precio_q_galon":"36.79"}]}
        refs=[{"foto_origen":"photo.HEIC","precio_super_manual":"36.19","revisor":"usuario_lectura_dudosa","confirmado_equipo":"false"}]
        result=evaluate(report,refs)
        self.assertEqual(result["fotos_con_referencia_humana"],0)
        self.assertFalse(result["cumple_minimo_20_fotos"])

    def test_named_reviewer_requires_explicit_confirmation(self):
        report = {"resultados": [{"foto_origen": "photo.HEIC", "combustible": "super", "precio_q_galon": "36.19"}]}
        reference = {"foto_origen": "photo.HEIC", "precio_super_manual": "36.19", "revisor": "equipo5"}
        self.assertEqual(evaluate(report, [reference])["fotos_con_referencia_humana"], 0)
        reference["confirmado_equipo"] = "true"
        self.assertEqual(evaluate(report, [reference])["fotos_con_referencia_humana"], 1)


if __name__ == "__main__":
    unittest.main()

class IllegibleReviewTests(unittest.TestCase):
    def test_confirmed_illegible_photo_counts_as_review_without_inventing_ground_truth(self):
        report={'resultados':[{'foto_origen':'photo.HEIC','combustible':'super','precio_q_galon':None}]}
        refs=[{'foto_origen':'photo.HEIC','revisor':'equipo','confirmado_equipo':'true','observaciones':'Las pantallas no se pueden leer'}]
        result=evaluate(report,refs)
        self.assertEqual(result['fotos_con_referencia_humana'],1)
        self.assertEqual(result['fotos_con_referencia_legible'],0)
        self.assertEqual(result['precios_esperados'],0)
        self.assertIsNone(result['exactitud_incluyendo_omisiones'])

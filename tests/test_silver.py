import unittest
from src.silver import clean_photos

class SilverTests(unittest.TestCase):
    def row(self,name='a',price='35.10',**values):
        return dict({'foto_origen':name,'fecha':'2026-10-20','combustible':'regular','precio_q_galon':price,'motivos_revision':[]},**values)
    def test_conflicting_prices_are_both_quarantined(self):
        accepted,rejected=clean_photos([self.row('a'),self.row('b','36.10')],{},'2026-11-20')
        self.assertTrue(accepted.empty);self.assertEqual(len(rejected),2)
        self.assertEqual(set(rejected.motivo_rechazo),{'PRECIOS_EN_CONFLICTO_MISMA_LLAVE'})
    def test_same_price_same_key_is_idempotently_deduplicated(self):
        rows=[self.row('b'),self.row('a')]
        first,_=clean_photos(rows,{},'2026-11-20');second,_=clean_photos(list(reversed(rows)),{},'2026-11-20')
        self.assertEqual(first.to_dict('records'),second.to_dict('records'));self.assertEqual(first.iloc[0].foto_origen,'a')
    def test_invalid_date_future_and_review_flag_cannot_be_accepted(self):
        rows=[self.row('a',fecha='bad'),self.row('b',fecha='2027-01-01'),self.row('c')]
        accepted,rejected=clean_photos(rows,{('c','regular'):'LECTURA_DUDOSA'},'2026-11-20')
        self.assertTrue(accepted.empty);self.assertEqual(len(rejected),3)
    def test_confirmed_human_disagreement_and_illegibility_do_not_enter_training(self):
        refs=[{'foto_origen':'a','revisor':'equipo','confirmado_equipo':'true','precio_regular_manual':'35.50'},
              {'foto_origen':'b','revisor':'equipo','confirmado_equipo':'true','precio_regular_manual':''}]
        accepted,rejected=clean_photos([self.row('a'),self.row('b')],{},'2026-11-20',refs)
        self.assertTrue(accepted.empty)
        self.assertIn('DISCREPA_REFERENCIA_HUMANA',rejected.iloc[0].motivo_rechazo)
        self.assertIn('REVISION_HUMANA_ILEGIBLE',rejected.iloc[1].motivo_rechazo)

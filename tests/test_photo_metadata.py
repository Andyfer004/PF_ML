import unittest
import pandas as pd
from src.photo_metadata import extract_metadata
from src.silver import clean_photos,extraction_summary


class PhotoMetadataTests(unittest.TestCase):
    def lines(self,*texts,confidence=.99):
        return [{'texto':t,'confianza':confidence} for t in texts]

    def test_explicit_values_and_evidence(self):
        result=extract_metadata(self.lines('Dirección: Km 18 carretera a El Salvador','AUTOSERVICIO'))
        self.assertEqual(result['ubicacion'],'Km 18 carretera a El Salvador')
        self.assertEqual(result['modalidad'],'autoservicio')
        self.assertIn('ubicacion',result['evidencia_metadatos'])

    def test_both_modes_cannot_be_assigned_to_all_prices(self):
        result=extract_metadata(self.lines('Autoservicio','Servicio completo'))
        self.assertEqual(result['modalidad'],'no_identificada')

    def test_ambiguous_locations_and_weak_ocr_abstain(self):
        result=extract_metadata(self.lines('Municipio: Mixco','Municipio: Guatemala'))
        self.assertEqual(result['ubicacion'],'no_identificada')
        self.assertEqual(extract_metadata(self.lines('Autoservicio',confidence=.89))['modalidad'],'no_identificada')

    def test_brand_prices_and_missing_markers_are_not_locations(self):
        result=extract_metadata(self.lines('Shell','Regular 35.19','Dirección: No visible'))
        self.assertEqual(result['ubicacion'],'no_identificada')
        self.assertEqual(result['modalidad'],'no_identificada')

    def test_full_service_and_repeated_views(self):
        result=extract_metadata(self.lines('Full service','Full service','Municipio: Mixco','Municipio: Mixco'))
        self.assertEqual(result['modalidad'],'servicio completo')
        self.assertEqual(result['ubicacion'],'Mixco')

    def test_photo_overlap_and_record_reasons(self):
        accepted=pd.DataFrame({'foto_origen':['a','a','b']})
        rejected=pd.DataFrame({'foto_origen':['a','c','c'],'motivo_rechazo':['X','X','Y']})
        result=extraction_summary(['a','b','c','d'],accepted,rejected)
        self.assertEqual(result['fotos_con_precios_aceptados'],2)
        self.assertEqual(result['fotos_sin_precios_aceptados'],2)
        self.assertEqual(result['fotos_con_algun_rechazo'],2)
        self.assertEqual(result['fotos_con_aceptados_y_rechazados'],1)
        self.assertEqual(sum(r['registros'] for r in result['rechazos_por_motivo']),3)

    def test_distinct_visible_stations_survive_quality_and_key_deduplication(self):
        rows=[]
        for station,price in [('Mixco','35.19'),('Antigua Guatemala','36.19')]:
            rows.append({'foto_origen':station,'fecha':'2026-11-24','combustible':'regular',
                         'precio_q_galon':price,'motivos_revision':[],
                         **extract_metadata(self.lines('Estación: '+station,'Autoservicio'))})
        accepted,rejected=clean_photos(rows,{},'2026-11-24')
        repeated,_=clean_photos(list(reversed(rows)),{},'2026-11-24')
        self.assertTrue(rejected.empty)
        self.assertEqual(len(accepted),2)
        self.assertEqual(set(accepted.ubicacion),{'Mixco','Antigua Guatemala'})
        self.assertEqual(accepted.to_dict('records'),repeated.to_dict('records'))


if __name__=='__main__':unittest.main()

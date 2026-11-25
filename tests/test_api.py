import copy,io,json,tempfile,unittest,uuid
from datetime import date,timedelta
from pathlib import Path
import pandas as pd
from fastapi.testclient import TestClient
from api.app.main import create_app
from api.app.store import GoldStore,GOLD_PREFIX

class MemoryStore:
    def __init__(self):
        self.manifest={'release':'a'*32,'fecha_corte':'2026-11-20','fuente_default':'mem'}
        self.tables={'precio_semanal':[{'fuente':source,'semana':week,'combustible':fuel,'precio_promedio':price} for source,week,fuel,price in [('mem','2026-11-17','super',36),('mem','2026-11-17','diesel',34),('mem','2026-11-10','super',35),('fotos','2026-10-13','super',40)]],
        'predicciones':[{'fuente':'mem','semana':'2026-11-24','combustible':'super','prediccion':'sube','probabilidad':.7}],
        'metricas_modelo':[{'fuente':'mem','fecha_corte':'2026-11-20','accuracy':.6,'baseline_accuracy':.5,'detalle_json':'{}'}]}
    def snapshot(self):return self.manifest,self.tables

class ApiTests(unittest.TestCase):
    def setUp(self):self.store=MemoryStore();self.client=TestClient(create_app(self.store,today=lambda:date(2026,11,20)))
    def test_filters_pagination_and_sources_do_not_mix(self):
        result=self.client.get('/precios?combustible=super&desde=2026-11-01&limit=1').json()
        self.assertEqual(result['total'],2);self.assertEqual(len(result['datos']),1)
        self.assertEqual(result['datos'][0]['precio_promedio'],36)
        photos=self.client.get('/precios?fuente=fotos').json();self.assertEqual(photos['total'],1)
    def historical_rows(self):
        self.store.tables['predicciones_historicas']=[
            {'fuente':'mem','semana':week,'semana_datos':(date.fromisoformat(week)-timedelta(days=7)).isoformat(),
             'fecha_corte_simulada':(date.fromisoformat(week)-timedelta(days=1)).isoformat(),'entrenamiento_hasta':'2026-01-05',
             'combustible':fuel,'prediccion':'baja','probabilidad':.8,'direccion_real':'sube',
             'generado_el':'2026-11-24T19:00:00-06:00'}
            for week,fuel in [('2026-11-03',f) for f in ('super','regular','diesel')]+[('2026-11-10','super')]]
    def test_historical_prediction_selects_same_complete_week_for_all_fuels(self):
        self.historical_rows()
        catalog=self.client.get('/prediccion/historica/semanas').json()
        self.assertEqual(catalog['semana_predeterminada'],'2026-11-03')
        for fuel in ('super','regular','diesel'):
            result=self.client.get('/prediccion/historica?combustible='+fuel)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['semana'],'2026-11-03')
            self.assertEqual(result.json()['modo'],'evaluacion_historica')
            self.assertFalse(result.json()['es_pronostico_vigente'])
        self.assertEqual(self.client.get('/prediccion/historica?combustible=super&fuente=fotos').status_code,404)
    def test_required_endpoint_defaults_to_explicit_historical_evaluation(self):
        self.historical_rows()
        for fuel in ('super','regular','diesel'):
            response=self.client.get('/prediccion?combustible='+fuel)
            self.assertEqual(response.status_code,200)
            result=response.json()
            self.assertEqual(result,self.client.get('/prediccion/historica?combustible='+fuel).json())
            self.assertEqual(result['semana'],'2026-11-03')
            self.assertEqual(result['fecha_corte_simulada'],'2026-11-02')
            self.assertEqual(result['modo'],'evaluacion_historica')
            self.assertFalse(result['es_pronostico_vigente'])
        # Aunque existe un pronóstico vigente en la fixture, el modo no cambia en silencio.
        self.assertEqual(self.client.get('/prediccion?combustible=super').json()['prediccion'],'baja')
        self.assertEqual(self.client.get('/prediccion?combustible=super&modo=vigente').json()['prediccion'],'sube')
    def test_required_endpoint_validates_mode_week_and_source(self):
        self.assertEqual(self.client.get('/prediccion?combustible=super').status_code,404)
        self.historical_rows()
        result=self.client.get('/prediccion?combustible=super&semana=2026-11-10')
        self.assertEqual(result.status_code,200);self.assertEqual(result.json()['semana_datos'],'2026-11-03')
        for query in ('modo=invalido','modo=vigente&semana=2026-11-03','semana=2026-11-04'):
            self.assertEqual(self.client.get('/prediccion?combustible=super&'+query).status_code,422)
        self.assertEqual(self.client.get('/prediccion?combustible=super&fuente=fotos').status_code,404)
        spec=self.client.get('/openapi.json').json()['paths']['/prediccion']['get']
        mode=next(p for p in spec['parameters'] if p['name']=='modo')
        self.assertEqual(mode['schema']['default'],'historica')
    def test_historical_invalid_week_missing_data_and_future_leak_are_rejected(self):
        self.assertEqual(self.client.get('/prediccion/historica?combustible=super').status_code,404)
        self.historical_rows()
        self.assertEqual(self.client.get('/prediccion/historica?combustible=super&semana=2026-11-04').status_code,422)
        self.assertEqual(self.client.get('/prediccion/historica?combustible=super&semana=2026-11-17').status_code,404)
        self.store.tables['predicciones_historicas'][0]['entrenamiento_hasta']='2026-11-24'
        result=self.client.get('/prediccion/historica?combustible=super&semana=2026-11-03')
        self.assertEqual(result.status_code,503)
    def test_invalid_fuel_dates_and_unbounded_limit_rejected(self):
        for query in ('combustible=vpower','desde=2026-11-20&hasta=2026-11-01','limit=1001','offset=-1'):
            self.assertEqual(self.client.get('/precios?'+query).status_code,422)
    def test_fresh_forecast_is_served_but_stale_forecast_is_blocked(self):
        self.assertEqual(self.client.get('/prediccion?combustible=super&modo=vigente').status_code,200)
        self.store.tables['predicciones'][0]['semana']='2026-11-17'
        result=self.client.get('/prediccion?combustible=super&modo=vigente')
        self.assertEqual(result.status_code,503);self.assertEqual(result.json()['detail']['codigo'],'DATOS_RECIENTES_INSUFICIENTES')
    def test_metrics_and_latest_prices(self):
        self.assertEqual(self.client.get('/modelo/metricas').json()['accuracy'],.6)
        actual=self.client.get('/precios/actual').json()['datos'];self.assertEqual(len(actual),2)
    def test_unavailable_gold_is_a_service_error_without_leaking_exception(self):
        class Broken:
            def snapshot(self):raise RuntimeError('secret-token')
        client=TestClient(create_app(Broken()))
        response=client.get('/health');self.assertEqual(response.status_code,503);self.assertNotIn('secret-token',response.text)
    def test_openapi_exposes_required_endpoints(self):
        spec=self.client.get('/openapi.json').json()
        for path in ('/health','/precios/actual','/precios','/prediccion','/modelo/metricas'):self.assertIn(path,spec['paths'])
    def test_dashboard_is_available_even_when_gold_is_unavailable(self):
        class Broken:
            def snapshot(self):raise RuntimeError('No S3')
        client=TestClient(create_app(Broken()))
        self.assertEqual(client.get('/health').status_code,503)
        page=client.get('/')
        self.assertEqual(page.status_code,200)
        self.assertIn('text/html',page.headers['content-type'])
        self.assertIn('Gasolina GT',page.text)
        self.assertEqual(client.get('/ui-assets/app.js').status_code,200)
        self.assertEqual(client.get('/ui-assets/styles.css').status_code,200)
    def test_project_summary_exposes_evidence_without_credentials(self):
        response=self.client.get('/proyecto/resumen')
        self.assertEqual(response.status_code,200)
        result=response.json()
        self.assertEqual(result['equipo'],5)
        self.assertIn('verificado_el',result)
        self.assertEqual([t['capa'] for t in result['pipeline']['tareas']],['bronze','silver','gold'])
        for sensitive in ('AWS_SECRET_ACCESS_KEY','AWS_ACCESS_KEY_ID','@uvg.edu.gt'):
            self.assertNotIn(sensitive,response.text)
    def test_dashboard_documents_are_whitelisted(self):
        response=self.client.get('/entregables/informe')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        for path in ('/entregables/.env','/entregables/README.md','/ui-assets/..%2f..%2f.env','/api/resources/proyecto.json'):
            self.assertEqual(self.client.get(path).status_code,404,path)

class StoreTests(unittest.TestCase):
    def test_local_release_is_loaded_from_explicit_parquet_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);release=uuid.uuid4().hex
            path=root/'file.parquet';pd.DataFrame([{'valor':1}]).to_parquet(path,index=False)
            manifest={'version':1,'release':release,'tablas':{n:['file.parquet'] for n in ('precio_semanal','variacion_semanal','predicciones','metricas_modelo')}}
            (root/'current.json').write_text(json.dumps(manifest));_,tables=GoldStore(root/'current.json').snapshot()
            self.assertEqual(tables['precio_semanal'],[{'valor':1}])
            manifest['tablas']['predicciones']=['../outside.parquet'];(root/'current.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):GoldStore(root/'current.json').snapshot()
    def test_s3_reader_never_follows_a_manifest_outside_gold_release(self):
        release='a'*32
        manifest={'version':1,'release':release,'tablas':{'precio_semanal':[GOLD_PREFIX+'releases/'+'b'*32+'/x.parquet']}}
        class Client:
            def get_object(self,**kwargs):return {'Body':io.BytesIO(json.dumps(manifest).encode())}
        with self.assertRaises(ValueError):GoldStore(GOLD_PREFIX+'current.json',client=Client()).snapshot()
        with self.assertRaises(ValueError):GoldStore('s3://other-bucket/data/current.json')

"""API de lectura de Oro. En el Droplet se publica únicamente sobre loopback."""
import json,os
from pathlib import Path
from datetime import date,datetime,timedelta
from enum import Enum
from zoneinfo import ZoneInfo
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .store import GoldStore,GOLD_PREFIX

class Fuel(str,Enum):
    super='super';regular='regular';diesel='diesel'
class Source(str,Enum):
    mem='mem';fotos='fotos'
class PredictionMode(str,Enum):
    historica='historica';vigente='vigente'

def day(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    return date.fromisoformat(str(value)[:10])

def create_app(store=None,today=None):
    app=FastAPI(title='Precios de combustibles de Guatemala',version='1.0.0')
    app.state.store=store or GoldStore(os.getenv('GOLD_MANIFEST',GOLD_PREFIX+'current.json'))
    now=today or (lambda:datetime.now(ZoneInfo('America/Guatemala')).date())
    root=Path(__file__).resolve().parents[2]
    ui=root/'api/ui'
    app.mount('/ui-assets',StaticFiles(directory=ui),name='ui-assets')

    @app.get('/',include_in_schema=False)
    @app.get('/dashboard',include_in_schema=False)
    def dashboard():
        return FileResponse(ui/'index.html',headers={
            'Cache-Control':'no-cache','X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"})

    @app.get('/proyecto/resumen')
    def project_summary():
        path=root/'api/resources/proyecto.json'
        if not path.is_file():raise HTTPException(status_code=503,detail='Resumen verificado no disponible')
        return json.loads(path.read_text())

    @app.get('/entregables/{documento}',include_in_schema=False)
    def document(documento:str):
        files={'informe':root/'docs/informe.pdf',
               'presentacion':root/'presentacion/presentacion_jurado.pdf',
               'resumen':root/'presentacion/resumen_jurado.pdf',
               'arquitectura':root/'docs/arquitectura_usuario.png'}
        path=files.get(documento)
        if path is None or not path.is_file():raise HTTPException(status_code=404,detail='Documento no disponible')
        return FileResponse(path,headers={'X-Content-Type-Options':'nosniff'})
    def load():
        try:return app.state.store.snapshot()
        except Exception:
            raise HTTPException(status_code=503,detail={'codigo':'ORO_NO_DISPONIBLE','mensaje':'No se pudo cargar una publicación completa de Oro.'})
    def source(value,manifest):return value.value if value else manifest.get('fuente_default','mem')

    @app.get('/health')
    def health():
        manifest,tables=load()
        return {'status':'ok','release':manifest['release'],'fecha_corte':manifest['fecha_corte'],'fuente_default':manifest['fuente_default'],'origen':manifest.get('origen','S3_ORO'),'validacion_ocr':manifest.get('validacion_ocr','PENDIENTE')}

    @app.get('/precios/actual')
    def current(fuente:Source|None=None):
        manifest,tables=load();cohort=source(fuente,manifest)
        latest={}
        for row in tables['precio_semanal']:
            if row['fuente']!=cohort:continue
            fuel=row['combustible']
            if fuel not in latest or day(row['semana'])>day(latest[fuel]['semana']):latest[fuel]=row
        return {'fuente':cohort,'datos':[dict(row,desactualizado=day(row['semana']) < now()-timedelta(days=(now().weekday()-1)%7)) for fuel,row in sorted(latest.items())]}

    @app.get('/precios')
    def prices(combustible:Fuel|None=None,desde:date|None=None,hasta:date|None=None,fuente:Source|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
        if desde and hasta and desde>hasta:raise HTTPException(status_code=422,detail='desde debe ser anterior o igual a hasta')
        manifest,tables=load();cohort=source(fuente,manifest)
        rows=[r for r in tables['precio_semanal'] if r['fuente']==cohort and (combustible is None or r['combustible']==combustible.value) and (desde is None or day(r['semana'])>=desde) and (hasta is None or day(r['semana'])<=hasta)]
        rows.sort(key=lambda r:(day(r['semana']),r['combustible']),reverse=True)
        return {'fuente':cohort,'total':len(rows),'limit':limit,'offset':offset,'datos':rows[offset:offset+limit]}

    @app.get('/prediccion',summary='Predicción semanal; demostración histórica por defecto')
    def prediction(combustible:Fuel,fuente:Source|None=None,modo:PredictionMode=PredictionMode.historica,semana:date|None=None):
        """Histórica: prueba reservada con corte simulado y resultado real posterior.

        Con modo=vigente se exige un pronóstico para el próximo martes de calendario.
        La semana opcional selecciona un martes de la evaluación histórica.
        """
        if modo==PredictionMode.historica:
            return historical_prediction(combustible=combustible,semana=semana,fuente=fuente)
        if semana is not None:
            raise HTTPException(status_code=422,detail='semana solo se utiliza en modo=historica')
        manifest,tables=load();cohort=source(fuente,manifest)
        target=now()+timedelta(days=(1-now().weekday())%7 or 7)
        rows=[r for r in tables['predicciones'] if r['fuente']==cohort and r['combustible']==combustible.value and day(r['semana'])==target]
        if not rows:
            raise HTTPException(status_code=503,detail={'codigo':'DATOS_RECIENTES_INSUFICIENTES','fuente':cohort,'combustible':combustible.value,'mensaje':'No hay un pronóstico vigente. Actualizar los precios de entrada; no se emiten predicciones vencidas.'})
        return dict(max(rows,key=lambda r:day(r['semana'])),modo='vigente',es_pronostico_vigente=True)

    def historical_rows(tables,cohort):
        return [r for r in tables.get('predicciones_historicas',[]) if r['fuente']==cohort]

    def historical_weeks(rows):
        weeks={}
        for row in rows:weeks.setdefault(day(row['semana']),set()).add(row['combustible'])
        return [{'semana':week,'combustibles':sorted(fuels),'tres_combustibles':len(fuels)==3}
                for week,fuels in sorted(weeks.items(),reverse=True)]

    @app.get('/prediccion/historica/semanas')
    def historical_catalog(fuente:Source|None=None):
        manifest,tables=load();cohort=source(fuente,manifest)
        weeks=historical_weeks(historical_rows(tables,cohort))
        default=next((r['semana'] for r in weeks if r['tres_combustibles']),weeks[0]['semana'] if weeks else None)
        return {'fuente':cohort,'modo':'evaluacion_historica','semana_predeterminada':default,'datos':weeks}

    @app.get('/prediccion/historica')
    def historical_prediction(combustible:Fuel,semana:date|None=None,fuente:Source|None=None):
        if semana and semana.weekday()!=1:
            raise HTTPException(status_code=422,detail='semana debe ser el martes de inicio de la semana objetivo')
        manifest,tables=load();cohort=source(fuente,manifest)
        rows=historical_rows(tables,cohort)
        weeks=historical_weeks(rows)
        target=semana or next((r['semana'] for r in weeks if r['tres_combustibles']),weeks[0]['semana'] if weeks else None)
        matches=[r for r in rows if r['combustible']==combustible.value and day(r['semana'])==target]
        if not matches:raise HTTPException(status_code=404,detail={'codigo':'SIN_EVALUACION_HISTORICA','mensaje':'No hay evaluación histórica reservada para esa fuente, semana y combustible.'})
        result=matches[0]
        if (not day(result['entrenamiento_hasta']) < day(result['semana_datos']) <= day(result['fecha_corte_simulada']) < day(result['semana'])
            or day(result['semana'])-day(result['semana_datos'])!=timedelta(days=7)
            or day(result['semana'])-day(result['fecha_corte_simulada'])!=timedelta(days=1)):
            raise HTTPException(status_code=503,detail={'codigo':'EVALUACION_HISTORICA_INVALIDA','mensaje':'Las fechas de la evaluación histórica no cumplen la separación temporal.'})
        return dict(result,modo='evaluacion_historica',es_pronostico_vigente=False)

    @app.get('/modelo/metricas')
    def model_metrics(fuente:Source|None=None):
        manifest,tables=load();cohort=source(fuente,manifest)
        rows=[r for r in tables['metricas_modelo'] if r['fuente']==cohort]
        if not rows:raise HTTPException(status_code=404,detail='Sin modelo evaluado para esta fuente')
        row=max(rows,key=lambda r:day(r['fecha_corte']))
        return {k:v for k,v in row.items() if k!='detalle_json'}
    return app

app=create_app()

"""Genera el resumen público del dashboard desde evidencia real, sin credenciales."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]

def build():
    destination=ROOT/'api/resources/proyecto.json'
    runs=[]
    for path in (ROOT/'output/ejecuciones').glob('*.json'):
        item=json.loads(path.read_text())
        if item.get('ejecucion',{}).get('state',{}).get('result_state')=='SUCCESS' and item.get('salidas',{}).get('silver'):
            runs.append(item)
    if not runs:
        if destination.exists():return destination
        raise ValueError('No existe evidencia de una ejecución completa para construir el resumen')
    runs.sort(key=lambda item:item['ejecucion'].get('start_time',0))
    latest=runs[-1];run=latest['ejecucion'];silver=latest['salidas']['silver'];human=silver['validacion_humana']
    settings=json.loads((ROOT/'pipelines/job_exportado.json').read_text())
    alert_path=ROOT/'docs/evidencia_alerta.json'
    alert=json.loads(alert_path.read_text()) if alert_path.exists() else {}
    tasks={}
    for task in run.get('tasks',[]):
        if task['task_key'] not in tasks or task.get('start_time',0)>tasks[task['task_key']].get('start_time',0):tasks[task['task_key']]=task
    report={
        'equipo':5,
        'verificado_el':datetime.fromtimestamp(run['end_time']/1000,ZoneInfo('America/Guatemala')).isoformat(),
        'pipeline':{'nombre':settings['name'],'estado':'SUCCESS','ejecuciones_validadas':len(runs),
                    'run_id':run['run_id'],
                    'url':f"https://dbc-5490c6a5-5215.cloud.databricks.com/?o=7474655525361249#job/{latest['job_id']}/run/{run['run_id']}",
                    'schedule':settings.get('schedule'),
                    'tareas':[{'capa':key,'estado':tasks[key]['state']['result_state'],
                               'duracion_segundos':tasks[key].get('execution_duration',0)//1000}
                              for key in ('bronze','silver','gold')]},
        'datos':{'fotos':silver['fotos'],'aceptados':silver['aceptados'],'rechazados':silver['rechazados'],
                 'observaciones_mem':next(t['filas'] for t in silver['tablas'] if t['tabla'].endswith('.precios_mem')),
                 'duplicados_nueva_carga':latest['salidas']['bronze']['new_files']},
        'ocr':{key:human[key] for key in ('fotos_revisadas','precios_esperados','precios_extraidos','precios_correctos',
                                        'exactitud_incluyendo_omisiones','cobertura','precision_sobre_extraidos')},
        'alertas':{'configuradas':bool(settings.get('email_notifications',{}).get('on_failure')),
                   'prueba_controlada_verificada':alert.get('fallo_controlado_verificado',False),
                   'recepcion_confirmada':alert.get('recepcion_correo_confirmada',False)},
        'reglas_calidad':['Combustible en el catálogo: súper, regular o diésel.',
                          'Precio entre Q10 y Q80 por galón.',
                          'Fecha válida y no posterior al corte.',
                          'Precios contradictorios en una misma llave van a rechazo.'],
        'documentos':[{'id':'informe','titulo':'Informe técnico','tipo':'PDF · 5 páginas'},
                       {'id':'presentacion','titulo':'Presentación','tipo':'PDF · 10 diapositivas'},
                       {'id':'resumen','titulo':'Resumen para el jurado','tipo':'PDF · 1 página'},
                       {'id':'arquitectura','titulo':'Arquitectura','tipo':'Diagrama · PNG'}],
        'estado_documentos':'Documentos de entrega del equipo',
        'nota':'Resumen de la última validación integral conservada. Los precios, predicciones y métricas se consultan en la API.'}
    phase4=ROOT/'output/verificacion_fase4.json'
    if phase4.exists():
        proof=json.loads(phase4.read_text())
        report['orquestacion']={'computo':proof['compute_mode'],
            'parametros_equipo':{'proyecto':proof['equipo'],'recursos_temporales':proof['equipo_recursos']},
            'evidencia':'Datos obtenidos de la API de Databricks; no son capturas del workspace.',
            'ejecuciones':[ {key:run[key] for key in ('run_id','foto','semana_foto','fecha_exif','resultado','duraciones_segundos','url')}
                            for run in proof['ejecuciones']]}
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return destination

if __name__=='__main__':print(build())

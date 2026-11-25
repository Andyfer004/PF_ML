"""Prueba autorizada de correo: falla antes del pipeline y restaura el Job.

Requiere confirmación explícita al ejecutar. Nunca modifica tablas ni dispara
las tareas Bronce, Plata u Oro. No comprueba la recepción en el buzón.
"""
import argparse
import base64
import copy
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.databricks_client import api

JOB_ID = 164482682079093
MARKER = 'PRUEBA_CONTROLADA_ALERTA_FALLO'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-email', action='store_true', required=True,
                        help='Autorizar el correo real de fallo al destinatario ya configurado')
    parser.parse_args()
    before = api('get', f'/api/2.1/jobs/get?job_id={JOB_ID}')
    owner = api('get', '/api/2.0/preview/scim/v2/Me')['userName']
    settings = before['settings']
    if before.get('creator_user_name') != owner or settings['name'] != 'equipo-03-pipeline':
        raise ValueError('El Job no pertenece al proyecto propio')
    if settings.get('email_notifications', {}).get('on_failure') != [owner]:
        raise ValueError('El destinatario debe ser únicamente la cuenta actual')
    active = api('get', f'/api/2.1/jobs/runs/list?job_id={JOB_ID}&active_only=true&limit=25')
    if active.get('runs'):
        raise RuntimeError('Hay ejecuciones activas; no se modifica el Job')
    token = uuid.uuid4().hex
    notebook = '/Users/' + owner + '/PF-ML/00_prueba_alerta_' + token
    task_key = 'prueba_controlada_alerta'
    report = {'fecha': datetime.now(ZoneInfo('America/Guatemala')).isoformat(),
              'job_id': JOB_ID, 'destinatario': owner,
              'idempotency_token': 'prueba-alerta-' + token,
              'recepcion_correo_confirmada': False,
              'configuracion_restaurada': False}
    evidence = ROOT / 'output/prueba_alerta_controlada.json'
    snapshot = ROOT / 'output/job_antes_prueba_alerta.json'
    snapshot.write_text(json.dumps(before, indent=2))

    def save():
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    altered = False
    created = False
    try:
        source = '# Databricks notebook source\nraise RuntimeError(' + repr(MARKER + ': fallo deliberado autorizado; sin escrituras de datos.') + ')\n'
        api('post', '/api/2.0/workspace/import', {
            'path': notebook, 'format': 'SOURCE', 'language': 'PYTHON',
            'overwrite': False, 'content': base64.b64encode(source.encode()).decode()})
        created = True
        temporary = copy.deepcopy(settings)
        if 'schedule' in temporary:
            temporary['schedule']['pause_status'] = 'PAUSED'
        for task in temporary['tasks']:
            task['depends_on'] = task.get('depends_on', []) + [{'task_key': task_key}]
            task['run_if'] = 'ALL_SUCCESS'
        temporary['tasks'].insert(0, {
            'task_key': task_key, 'notebook_task': {'notebook_path': notebook},
            'max_retries': 0, 'timeout_seconds': 300})
        altered = True  # Restaurar incluso si la respuesta de la mutación agota el tiempo.
        save()
        api('post', '/api/2.1/jobs/reset', {'job_id': JOB_ID, 'new_settings': temporary})
        run_id = api('post', '/api/2.1/jobs/run-now', {
            'job_id': JOB_ID, 'idempotency_token': report['idempotency_token']})['run_id']
        report['run_id'] = run_id
        save()
        print(json.dumps({'run_id': run_id, 'destinatario': owner}), flush=True)
        deadline = time.monotonic() + 480
        previous = None
        while True:
            run = api('get', f'/api/2.1/jobs/runs/get?run_id={run_id}')
            report['ejecucion'] = run
            save()
            state = run['state']
            if state != previous:
                print(json.dumps(state), flush=True)
                previous = state
            if state['life_cycle_state'] in ('TERMINATED', 'INTERNAL_ERROR', 'SKIPPED', 'BLOCKED'):
                break
            if time.monotonic() > deadline:
                api('post', '/api/2.1/jobs/runs/cancel', {'run_id': run_id})
                raise TimeoutError('Prueba cancelada por exceder ocho minutos')
            time.sleep(8)
        task = next(t for t in run['tasks'] if t['task_key'] == task_key)
        output = api('get', f"/api/2.1/jobs/runs/get-output?run_id={task['run_id']}")
        report['error_controlado'] = output.get('error', '')
        report['tareas_pipeline_ejecutadas'] = [
            t['task_key'] for t in run['tasks']
            if t['task_key'] != task_key and t.get('execution_duration', 0) > 0]
        if state.get('result_state') != 'FAILED' or MARKER not in report['error_controlado']:
            raise RuntimeError('No se confirmó el fallo deliberado esperado')
        if report['tareas_pipeline_ejecutadas']:
            raise RuntimeError('Se ejecutó una tarea que debía quedar bloqueada')
        report['fallo_controlado_verificado'] = True
    finally:
        if altered:
            api('post', '/api/2.1/jobs/reset', {'job_id': JOB_ID, 'new_settings': settings})
            after = api('get', f'/api/2.1/jobs/get?job_id={JOB_ID}')
            report['configuracion_restaurada'] = after['settings'] == settings
            if not report['configuracion_restaurada']:
                report['campos_distintos'] = [k for k in set(settings) | set(after['settings'])
                                             if settings.get(k) != after['settings'].get(k)]
            (ROOT / 'output/job_exportado.json').write_text(json.dumps(after, indent=2))
            (ROOT / 'pipelines/job_exportado.json').write_text(json.dumps(after['settings'], indent=2) + '\n')
        if created:
            try:
                api('post', '/api/2.0/workspace/delete', {'path': notebook, 'recursive': False})
                report['notebook_temporal_eliminado'] = True
            except Exception as exc:
                report['error_limpieza'] = str(exc)
        save()
    if not report['configuracion_restaurada']:
        raise RuntimeError('Revisar restauración del Job antes de otra ejecución')
    print(json.dumps({k: v for k, v in report.items() if k != 'ejecucion'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

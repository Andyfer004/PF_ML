"""Crea/actualiza el Job propio y registra resultados; conserva la alerta configurada de fallos."""
import argparse,json,subprocess,sys,time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]

import sys
sys.path.insert(0,str(ROOT))
from src.databricks_client import api

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-path',default='s3://cc3105-raw-869227452861-us-east-2-an/img/')
    parser.add_argument('--fecha-corte',default=datetime.now(ZoneInfo('America/Guatemala')).date().isoformat())
    parser.add_argument('--equipo',default='03')
    parser.add_argument('--equipo-recursos',default='05')
    schedule_group=parser.add_mutually_exclusive_group()
    schedule_group.add_argument('--activate-schedule',action='store_true')
    schedule_group.add_argument('--pause-schedule',action='store_true')
    parser.add_argument('--repair-run',type=int)
    parser.add_argument('--compute',choices=('serverless','classic'),help='Cambiar explícitamente el cómputo; sin este parámetro se conserva el del Job existente')
    args=parser.parse_args()
    from src.lakehouse import validate_identity
    identity=validate_identity({'equipo':args.equipo,'equipo_recursos':args.equipo_recursos})
    if not args.source_path.startswith('s3://cc3105-raw-869227452861-us-east-2-an/img/') or '..' in args.source_path.split('/'):raise ValueError('Origen no autorizado')
    filename='antecedentes/job_classic.json' if args.compute=='classic' else 'job.json'
    settings=json.loads((ROOT/'pipelines'/filename).read_text())
    if args.activate_schedule:settings['schedule']['pause_status']='UNPAUSED'
    if args.repair_run:
        original=api('get',f'/api/2.1/jobs/runs/get?run_id={args.repair_run}')
        owner=api('get','/api/2.0/preview/scim/v2/Me')['userName']
        if original.get('creator_user_name')!=owner or original.get('run_name') not in ('equipo-03-pipeline','equipo-05-pipeline'):raise ValueError('La ejecución no pertenece al Job propio')
        job_id=original['job_id'];run_id=args.repair_run
        request={'run_id':run_id,'rerun_tasks':['gold'],'rerun_dependent_tasks':True}
        if original.get('repair_history'):request['latest_repair_id']=original['repair_history'][-1]['id']
        api('post','/api/2.1/jobs/runs/repair',request)
    else:
        jobs=[]
        for name in (settings['name'],'equipo-05-pipeline'):
            response=api('get',f'/api/2.1/jobs/list?name={name}&limit=100')
            jobs.extend(j for j in response.get('jobs',[]) if j['settings']['name']==name and j['job_id'] not in {v['job_id'] for v in jobs})
        if len(jobs)>1:raise ValueError('Hay varios Jobs con el nombre del proyecto; resolver antes de actualizar')
        if jobs:
            owner=api('get','/api/2.0/preview/scim/v2/Me')['userName']
            if jobs[0].get('creator_user_name')!=owner:raise ValueError('El Job existente pertenece a otra identidad')
            job_id=jobs[0]['job_id']
            existing=api('get',f'/api/2.1/jobs/get?job_id={job_id}')
            if args.compute is None:
                current=existing['settings']
                for field in ('job_clusters','environments'):
                    if field in current:settings[field]=current[field]
                tasks={task['task_key']:task for task in current.get('tasks',[])}
                for task in settings['tasks']:
                    for field in ('job_cluster_key','existing_cluster_id','new_cluster','environment_key'):
                        if field in tasks.get(task['task_key'],{}):task[field]=tasks[task['task_key']][field]
            if not args.activate_schedule and not args.pause_schedule:
                settings['schedule']=existing['settings'].get('schedule',settings['schedule'])
            classic=any(any(field in task for field in ('job_cluster_key','existing_cluster_id','new_cluster')) for task in settings['tasks'])
            for parameter in settings['parameters']:
                if parameter['name']=='compute_mode':parameter['default']='classic' if classic else 'serverless'
            api('post','/api/2.1/jobs/reset',{'job_id':job_id,'new_settings':settings})
        else:job_id=api('post','/api/2.1/jobs/create',settings)['job_id']
        run_id=api('post','/api/2.1/jobs/run-now',{'job_id':job_id,'job_parameters':{'fecha_corte':args.fecha_corte,'source_path':args.source_path,'equipo':identity['equipo'],'equipo_recursos':identity['equipo_recursos']}})['run_id']
    print(json.dumps({'job_id':job_id,'run_id':run_id}),flush=True)
    directory=ROOT/'output/ejecuciones';directory.mkdir(exist_ok=True,parents=True)
    destination=directory/f'{run_id}.json';last=None
    while True:
        run=api('get',f'/api/2.1/jobs/runs/get?run_id={run_id}');state=run['state']
        destination.write_text(json.dumps({'config':vars(args),'job_id':job_id,'ejecucion':run},ensure_ascii=False,indent=2))
        status=[(t['task_key'],t.get('state',{}).get('life_cycle_state'),t.get('state',{}).get('result_state')) for t in run.get('tasks',[])]
        if status!=last:print(json.dumps(status),flush=True);last=status
        if state['life_cycle_state'] in ('TERMINATED','SKIPPED','INTERNAL_ERROR','BLOCKED'):break
        time.sleep(15)
    output={'config':vars(args),'job_id':job_id,'ejecucion':run,'salidas':{}}
    latest={}
    for task in run.get('tasks',[]):
        key=task['task_key']
        if key not in latest or task.get('start_time',0)>latest[key].get('start_time',0):latest[key]=task
    for task in latest.values():
        if task.get('run_id'):
            response=api('get',f"/api/2.1/jobs/runs/get-output?run_id={task['run_id']}")
            raw=response.get('notebook_output',{}).get('result')
            output['salidas'][task['task_key']]=json.loads(raw) if raw else response
    destination.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps({'estado':state,'evidencia':str(destination)},ensure_ascii=False))
    if state.get('result_state')!='SUCCESS':sys.exit(1)

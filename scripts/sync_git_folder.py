"""Sincroniza el repositorio público en el Git folder propio y, opcionalmente, conecta el Job."""
import argparse
import copy
import json
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.databricks_client import api

URL = 'https://github.com/Andyfer004/PF_ML.git'
USER = 'fue22944@uvg.edu.gt'
FOLDER = '/Users/' + USER + '/PF_ML'
JOB_ID = 164482682079093


def sync(update_job=False):
    if api('get', '/api/2.0/preview/scim/v2/Me')['userName'] != USER:
        raise ValueError('La sesión no corresponde al usuario autorizado del proyecto')
    repos = api('get', '/api/2.0/repos?path_prefix=' + quote(FOLDER, safe=''))
    matches = [r for r in repos.get('repos', []) if r['path'] == FOLDER]
    if len(matches) > 1:
        raise ValueError('Hay varios Git folders con la misma ruta')
    if matches:
        repo = matches[0]
        if repo['url'].rstrip('/').removesuffix('.git') != URL.removesuffix('.git'):
            raise ValueError('El Git folder apunta a otro repositorio')
    else:
        repo = api('post', '/api/2.0/repos', {'url': URL, 'provider': 'gitHub', 'path': FOLDER})
    repo_id = repo['id']
    api('patch', f'/api/2.0/repos/{repo_id}', {'branch': 'main'})
    repo = api('get', f'/api/2.0/repos/{repo_id}')
    objects = api('get', '/api/2.0/workspace/list?path=' + quote(FOLDER + '/pipelines', safe=''))
    paths = {}
    for layer in ('bronze', 'silver', 'gold'):
        name = {'bronze': '01_bronze', 'silver': '02_silver', 'gold': '03_gold'}[layer]
        found = [o['path'] for o in objects.get('objects', [])
                 if Path(o['path']).name in (name, name + '.py') and o.get('object_type') == 'NOTEBOOK']
        if len(found) != 1:
            raise ValueError('No se encontró exactamente un notebook de ' + layer)
        paths[layer] = found[0]
    proof = {'equipo': 5, 'repo_id': repo_id, 'url': URL, 'path': FOLDER,
             'branch': repo.get('branch'), 'head_commit_id': repo.get('head_commit_id'),
             'notebooks': paths, 'job_id': JOB_ID, 'job_conectado': False}
    if update_job:
        job = api('get', f'/api/2.1/jobs/get?job_id={JOB_ID}')
        if job.get('creator_user_name') != USER:
            raise ValueError('El Job no pertenece al usuario del proyecto')
        settings = copy.deepcopy(job['settings'])
        (ROOT / 'output/gitfolders').mkdir(parents=True, exist_ok=True)
        (ROOT / 'output/gitfolders/job_antes_gitfolder.json').write_text(json.dumps(settings, indent=2))
        if {t['task_key'] for t in settings['tasks']} != set(paths):
            raise ValueError('Las tareas del Job no coinciden con las tres capas esperadas')
        for task in settings['tasks']:
            task['notebook_task']['notebook_path'] = paths[task['task_key']]
            task['notebook_task']['source'] = 'WORKSPACE'
        for parameter in settings['parameters']:
            if parameter['name'] == 'workspace_path':
                parameter['default'] = '/Workspace' + FOLDER
        api('post', '/api/2.1/jobs/update', {'job_id': JOB_ID, 'new_settings': {
            'tasks': settings['tasks'], 'parameters': settings['parameters']}})
        actual = api('get', f'/api/2.1/jobs/get?job_id={JOB_ID}')['settings']
        if any(t['notebook_task']['notebook_path'] != paths[t['task_key']] for t in actual['tasks']):
            raise ValueError('El Job no conserva las rutas esperadas del Git folder')
        (ROOT / 'pipelines/job_exportado.json').write_text(json.dumps(actual, ensure_ascii=False, indent=2) + '\n')
        template = copy.deepcopy(actual)
        template['schedule']['pause_status'] = 'PAUSED'
        (ROOT / 'pipelines/job.json').write_text(json.dumps(template, ensure_ascii=False, indent=2) + '\n')
        proof['job_conectado'] = True
    destination = ROOT / 'docs/evidencias/gitfolders.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-job', action='store_true')
    sync(parser.parse_args().update_job)

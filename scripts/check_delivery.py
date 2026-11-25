"""Audita artefactos y evidencia local; no configura servicios ni envía mensajes."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def audit():
    required = [
        'README.md', 'docs/arquitectura_usuario.png',
        'docs/evidencias/fase4/historial_job.png',
        'docs/evidencias/fase4/ejecucion_128298002079637.png',
        'docs/evidencias/fase4/ejecucion_592769852166445.png',
        'pipelines/01_bronze.py', 'pipelines/02_silver.py', 'pipelines/03_gold.py',
        'pipelines/job.json', 'pipelines/job_exportado.json',
        'pipelines/computo_documentado.json',
        'api/app/main.py', 'api/Dockerfile', 'api/compose.yaml', 'api/.env.example',
        'tests/consultas_api.sh', 'data/evaluacion_ocr_confirmada.csv',
        '.github/workflows/pruebas.yml', 'requirements-test.txt',
        'api/ui/index.html', 'api/ui/styles.css', 'api/ui/app.js', 'api/resources/proyecto.json',
    ]
    missing = [name for name in required if not (ROOT / name).is_file()]
    documents = {}
    for name, maximum in [('docs/informe.pdf', 5),
                          ('presentacion/presentacion_jurado.pdf', None),
                          ('presentacion/resumen_jurado.pdf', 1)]:
        path = ROOT / name
        if not path.is_file():
            missing.append(name)
            continue
        pages = len(PdfReader(path).pages)
        documents[name] = {'paginas': pages, 'cumple_extension': maximum is None or 0 < pages <= maximum}
    runs = []
    for path in (ROOT / 'output/ejecuciones').glob('*.json'):
        record = json.loads(path.read_text())
        run = record.get('ejecucion', {})
        if run.get('state', {}).get('result_state') != 'SUCCESS':
            continue
        runs.append({'run_id': run['run_id'], 'tareas': [
            {k: task.get(k) for k in ('task_key', 'run_id', 'execution_duration', 'setup_duration', 'state')}
            for task in run.get('tasks', [])]})
    # La evidencia API no reemplaza la captura de UI ni una prueba externa del Droplet.
    droplet_path = ROOT / 'output/resultado_droplet.json'
    droplet = json.loads(droplet_path.read_text()) if droplet_path.exists() else {}
    gold_ok = droplet.get('health', {}).get('status') == 'ok' and droplet.get('health', {}).get('origen') == 'S3_ORO'
    public_path=ROOT/'output/verificacion_api_publica.json'
    public=json.loads(public_path.read_text()) if public_path.exists() else {}
    public_ok=public.get('probado_desde_fuera_del_droplet',False) and public.get('endpoints',{}).get('/health',{}).get('http')==200
    pending = [] if gold_ok else ['AWS: habilitar y probar GetObject de Oro desde la identidad real del Droplet.']
    job_path = ROOT / 'pipelines/job_exportado.json'
    job = json.loads(job_path.read_text()) if job_path.exists() else {}
    recipients = job.get('email_notifications', {}).get('on_failure', [])
    if not recipients:
        pending.append('Alertas: configurar correo para fallos del Job.')
    professor_path=ROOT/'output/verificacion_acceso_profesor.json'
    professor=json.loads(professor_path.read_text()) if professor_path.exists() else {}
    professor_ok=professor.get('puede_disparar_job_por_permiso',False) and all(
        e.get('puede_administrar',False) for e in professor.get('experimentos_mlflow',[])) and bool(professor.get('experimentos_mlflow'))
    if not professor_ok:pending.append('Permisos: comprobar acceso de la cuenta del profesor al Job y a MLflow.')
    gitfolder_path=ROOT/'docs/evidencias/gitfolders.json'
    gitfolder=json.loads(gitfolder_path.read_text()) if gitfolder_path.exists() else {}
    ci_path=ROOT/'docs/evidencias/github_actions.json'
    ci=json.loads(ci_path.read_text()) if ci_path.exists() else {}
    return {
        'fecha': datetime.now(ZoneInfo('America/Guatemala')).isoformat(),
        'archivos_faltantes': missing,
        'documentos': documents,
        'ejecuciones_exitosas': runs,
        'api_lee_oro_s3': gold_ok,
        'api_publica_verificada':public_ok,
        'url_publica':public.get('url_publica') if public_ok else None,
        'alertas_fallo_configuradas': bool(recipients),
        'destinatarios_alerta_fallo': recipients,
        'acceso_profesor_verificado_por_acl':professor_ok,
        'gitfolder_conectado':gitfolder.get('job_conectado',False),
        'github_actions_verificado':ci.get('conclusion')=='success',
        'capturas_adjuntas':all((ROOT/'docs/evidencias/fase4'/name).is_file() for name in ('historial_job.png','ejecucion_128298002079637.png','ejecucion_592769852166445.png')),
        'pendientes_externos_o_manuales': pending + [
            'Computo: el workspace acepta solo serverless; queda pendiente la conformidad docente frente al requisito de clusters clasicos.',
            'Equipo: incorporar aportes reales de los demas integrantes; no se inventan autorias.',
            'Presentacion: conservar un respaldo para la demo; las tres capturas del Job ya estan en docs/evidencias/fase4/.',
            ('Presentacion: entregar el resumen con la URL publica 48 horas antes.' if public_ok else 'Presentacion: confirmar puerto publico asignado, probar desde fuera y entregar resumen 48 horas antes.'),
        ],
        'limite': 'Esta auditoria local no certifica permisos remotos, capturas ni publicacion.',
    }


if __name__ == '__main__':
    result = audit()
    destination = ROOT / 'output/auditoria_entrega.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('archivos_faltantes', 'documentos', 'pendientes_externos_o_manuales')}, ensure_ascii=False, indent=2))
    if result['archivos_faltantes'] or not all(v['cumple_extension'] for v in result['documentos'].values()):
        raise SystemExit(1)

"""Prepara una copia revisable del repositorio sin secretos ni fotos originales."""
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    audit = json.loads((ROOT / 'output/auditoria_entrega.json').read_text())
    api = json.loads((ROOT / 'output/resultado_droplet.json').read_text())
    evidence = {
        'fecha': datetime.now(ZoneInfo('America/Guatemala')).isoformat(),
        'fuente': 'Databricks Jobs API y HTTP por SSH al Droplet; no son capturas de UI',
        'ejecuciones': audit['ejecuciones_exitosas'],
        'api': {path: {'http': response['status']} for path, response in api['endpoints'].items()},
        'publicacion_oro': api.get('health'),
        'pendientes': audit['pendientes_externos_o_manuales'],
    }
    notification_evidence = ROOT / 'docs/evidencia_alerta.json'
    if notification_evidence.exists():
        evidence['prueba_alerta_fallo'] = json.loads(notification_evidence.read_text())
    silver_evidence = ROOT / 'output/verificacion_plata_metadatos.json'
    if silver_evidence.exists():
        silver = json.loads(silver_evidence.read_text())
        evidence['validacion_plata'] = {key:silver[key] for key in (
            'primera_ejecucion','segunda_ejecucion','firma_codigo',
            'tablas_identicas','resumen_identico','resumen')}
    historical_evidence = ROOT / 'output/verificacion_historica_droplet.json'
    if historical_evidence.exists():
        evidence['evaluacion_historica'] = json.loads(historical_evidence.read_text())
    orchestration_evidence=ROOT/'output/verificacion_fase4.json'
    if orchestration_evidence.exists():
        evidence['orquestacion_fase4']=json.loads(orchestration_evidence.read_text())
    public_evidence=ROOT/'output/verificacion_api_publica.json'
    if public_evidence.exists():
        evidence['api_publica']=json.loads(public_evidence.read_text())
    prediction_evidence=ROOT/'output/verificacion_endpoint_prediccion_publico.json'
    if prediction_evidence.exists():
        evidence['endpoint_prediccion']=json.loads(prediction_evidence.read_text())
    credential_evidence=ROOT/'output/verificacion_credenciales_env.json'
    if credential_evidence.exists():
        evidence['credenciales_api']=json.loads(credential_evidence.read_text())
    (ROOT / 'docs/evidencia_operativa.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    raw = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard', '-z'],
                         cwd=ROOT, capture_output=True, check=True).stdout.decode()
    names = sorted(set(filter(None, raw.split('\0'))))
    files = []
    forbidden = {'.git', '.aws', '.ssh', '.codex', '.cache', '.venv', 'tmp'}
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        if forbidden.intersection(Path(name).parts) or (path.name.startswith('.env') and path.name != '.env.example'):
            raise ValueError('Archivo privado seleccionado: ' + name)
        if name.startswith('data/images/') and path.name != '.gitkeep':
            raise ValueError('Fotografía original seleccionada: ' + name)
        files.append((name, path.read_bytes()))
    manifest = {'fecha': evidence['fecha'], 'archivos': [
        {'ruta': name, 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}
        for name, blob in files]}
    intro = ('ESTADO PARA REVISION - EQUIPO 5\n\n'
             'Pipeline y API con lectura real de Oro verificados.\n'
             'Revisar README.md, docs/informe.pdf y presentacion/.\n'
             'Equipo 5; cuenta SSH asignada cc3105-03.\n'
             'Esta copia no publica cambios en GitHub ni habilita acceso publico.\n\n'
             'Pendientes reales:\n' + ''.join('- ' + p + '\n' for p in evidence['pendientes']))
    destination = ROOT / 'output/PF_ML_revision.zip'
    with ZipFile(destination, 'w', compression=ZIP_DEFLATED) as archive:
        for name, blob in files:
            archive.writestr('PF_ML/' + name, blob)
        archive.writestr('PF_ML/REVISAR.txt', intro)
        archive.writestr('PF_ML/MANIFIESTO_REVISION.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP inválido')
    print(json.dumps({'paquete': str(destination), 'archivos': len(files), 'bytes': destination.stat().st_size}, ensure_ascii=False))

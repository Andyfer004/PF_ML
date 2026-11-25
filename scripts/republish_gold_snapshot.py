"""Republica la copia verificada de Oro en S3; conserva su corte y procedencia.

Respaldo explícito cuando vence la sesión de Databricks. No prepara datos nuevos,
no entrena modelos y no sustituye actualizar el publicador del Job.
"""
import base64
import hashlib
import json
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.api_publication import API_ROOT, TABLES


if __name__ == '__main__':
    directory = ROOT / 'output/api_oro_real'
    original = json.loads((directory / 'manifest_s3_original.json').read_text())
    local = json.loads((directory / 'current.json').read_text())
    if original['release'] != local['release'] or original['fecha_corte'] != local['fecha_corte']:
        raise ValueError('La copia y su manifiesto original no corresponden')
    release = uuid.uuid4().hex
    manifest = dict(original, release=release, tablas={}, equipo_proyecto=3,
                    identidad_aws_temporal='cc3105-equipo5',
                    release_origen=original['release'],
                    publicacion_metodo='REPUBLICACION_COPIA_EXPORTADA_DE_ORO',
                    fecha_publicacion=datetime.now(timezone.utc).isoformat())
    files = {}
    for table in TABLES:
        if not original['tablas'].get(table) or len(original['tablas'][table]) != len(local['tablas'][table]):
            raise ValueError('Exportación incompleta: ' + table)
        manifest['tablas'][table] = []
        for index, relative in enumerate(local['tablas'][table]):
            path = (directory / relative).resolve()
            if not path.is_relative_to((directory / 'releases' / local['release']).resolve()):
                raise ValueError('Archivo fuera de la copia verificada')
            blob = path.read_bytes()
            if not blob.startswith(b'PAR1') or not blob.endswith(b'PAR1'):
                raise ValueError('Parquet inválido')
            url = API_ROOT + 'releases/' + release + '/' + table + '/' + str(index) + '.parquet'
            manifest['tablas'][table].append(url)
            files[url] = {'contenido': base64.b64encode(blob).decode(), 'sha256': hashlib.sha256(blob).hexdigest()}
    payload = json.dumps({'manifest': manifest, 'files': files}).encode()
    code = '''import base64,hashlib,json,sys,boto3
from urllib.parse import urlparse
p=json.load(sys.stdin);s=boto3.Session()
identity=s.client('sts',region_name='us-east-2').get_caller_identity()['Arn']
if identity!='arn:aws:iam::869227452861:user/cc3105-equipo5':raise ValueError('Identidad temporal distinta de la autorizada')
c=s.client('s3',region_name='us-east-2');root='s3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/'
release=p['manifest']['release'];checks=[]
for url,item in p['files'].items():
 if not url.startswith(root+'releases/'+release+'/'):raise ValueError('Ruta fuera de la publicación')
 u=urlparse(url);blob=base64.b64decode(item['contenido'],validate=True)
 if hashlib.sha256(blob).hexdigest()!=item['sha256']:raise ValueError('SHA local incorrecto')
 c.put_object(Bucket=u.netloc,Key=u.path.lstrip('/'),Body=blob,IfNoneMatch='*')
 downloaded=c.get_object(Bucket=u.netloc,Key=u.path.lstrip('/'))['Body'].read()
 if hashlib.sha256(downloaded).hexdigest()!=item['sha256']:raise ValueError('SHA remoto incorrecto')
 checks.append({'ruta':url,'sha256':item['sha256'],'bytes':len(blob)})
blob=json.dumps(p['manifest'],ensure_ascii=False).encode();u=urlparse(root)
c.put_object(Bucket=u.netloc,Key=u.path.lstrip('/')+'releases/'+release+'/manifest.json',Body=blob,ContentType='application/json',IfNoneMatch='*')
c.put_object(Bucket=u.netloc,Key=u.path.lstrip('/')+'current.json',Body=blob,ContentType='application/json')
print(json.dumps({'identidad':identity,'release':release,'fecha_corte':p['manifest']['fecha_corte'],'archivos_verificados':checks,'manifest':root+'current.json'}))
'''
    command = 'docker exec -i cc3105-03-equipo05-api-1 python -c ' + shlex.quote(code)
    result = subprocess.run(['ssh', '-i', str(Path.home() / '.ssh/proyecto_ed25519'),
                             '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                             '-o', 'StrictHostKeyChecking=yes', 'cc3105-03@165.22.137.8', command],
                            input=payload, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode())
    report = json.loads(result.stdout)
    (ROOT / 'output/republicacion_oro_temporal.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))

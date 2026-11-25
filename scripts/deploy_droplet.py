"""Despliega la API propia y conserva su interfaz de publicación; no cambia el firewall."""
import argparse,json,shlex,subprocess,tarfile,tempfile,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

if __name__=='__main__':
    from build_dashboard_summary import build
    build()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',default='165.22.137.8');p.add_argument('--user',default='cc3105-03')
    p.add_argument('--key',type=Path,default=Path.home()/'.ssh/proyecto_ed25519');p.add_argument('--port',type=int,default=8000)
    p.add_argument('--bind-host',choices=('127.0.0.1','0.0.0.0'),help='Sin este parámetro conserva la publicación del servidor; una instalación nueva usa loopback')
    p.add_argument('--import-server-credentials',action='store_true',help='Importar al .env el perfil AWS existente, únicamente dentro del Droplet y sin mostrar claves')
    p.add_argument('--allow-unavailable-gold',action='store_true',help='Instalar y arrancar la API con 503 explícito mientras se habilita GetObject')
    a=p.parse_args()
    if (a.host,a.user)!=('165.22.137.8','cc3105-03'):raise ValueError('Destino distinto de la cuenta confirmada')
    if not 1024<=a.port<=65535:raise ValueError('Puerto local inválido')
    if a.bind_host=='0.0.0.0' and a.port!=8000:raise ValueError('La publicación pública autorizada corresponde al puerto 8000')
    address=a.user+'@'+a.host;token=uuid.uuid4().hex
    flags=['-i',str(a.key),'-o','BatchMode=yes','-o','ConnectTimeout=15','-o','StrictHostKeyChecking=yes']
    with tempfile.TemporaryDirectory() as directory:
        archive=Path(directory)/('equipo05-'+token+'.tar.gz')
        with tarfile.open(archive,'w:gz') as tar:
            documents=[ROOT/name for name in ('docs/informe.pdf','docs/arquitectura_usuario.png','presentacion/presentacion_jurado.pdf','presentacion/resumen_jurado.pdf')]
            for file in [ROOT/'requirements-api.txt',ROOT/'requirements-api.lock',ROOT/'.dockerignore',*documents,*list((ROOT/'api').rglob('*'))]:
                if file.is_file() and '__pycache__' not in file.parts and (not file.name.startswith('.env') or file.name=='.env.example'):tar.add(file,arcname=str(file.relative_to(ROOT)))
        remote_archive='/home/cc3105-03/'+archive.name
        subprocess.run(['scp',*flags,str(archive),address+':'+remote_archive],check=True)
    script='''import json,os,pathlib,socket,subprocess,tarfile,re
home=pathlib.Path.home();app=home/'gasolina-equipo-05';app.mkdir(exist_ok=True)
archive=home/ARCHIVE_NAME
with tarfile.open(archive) as tar:
 for item in tar.getmembers():
  target=(app/item.name).resolve()
  if not target.is_relative_to(app.resolve()):raise ValueError('Ruta fuera del proyecto')
 tar.extractall(app,filter='data')
archive.unlink()
uid,gid=os.getuid(),os.getgid()
env=app/'api/.env'
if not env.exists():
 write_env_atomic(env,update_env('',{'GOLD_MANIFEST':'s3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/current.json','AWS_DEFAULT_REGION':'us-east-2','APP_UID':str(uid),'APP_GID':str(gid)}))
# Actualizar solo la ubicación de Oro; conservar cualquier otra configuración.
write_env_atomic(env,update_env(env.read_text(),{'GOLD_MANIFEST':'s3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/current.json'}))
# Las claves se obtienen y guardan dentro del servidor, nunca en el cliente SSH.
import boto3
if IMPORT_SERVER_CREDENTIALS:
 credentials=boto3.Session().get_credentials()
 if credentials is None:raise RuntimeError('El usuario del servidor no tiene credenciales AWS')
 frozen=credentials.get_frozen_credentials()
 updates={'AWS_ACCESS_KEY_ID':frozen.access_key,'AWS_SECRET_ACCESS_KEY':frozen.secret_key,'AWS_SESSION_TOKEN':frozen.token,
          'AWS_PROFILE':None,'AWS_DEFAULT_PROFILE':None,'AWS_SHARED_CREDENTIALS_FILE':None,'AWS_CONFIG_FILE':None}
 write_env_atomic(env,update_env(env.read_text(),updates))
settings=parse_env(env.read_text())
if not settings.get('AWS_ACCESS_KEY_ID') or not settings.get('AWS_SECRET_ACCESS_KEY'):
 raise RuntimeError('Configurar credenciales en el .env del servidor o usar --import-server-credentials')
session=boto3.Session(aws_access_key_id=settings['AWS_ACCESS_KEY_ID'],aws_secret_access_key=settings['AWS_SECRET_ACCESS_KEY'],aws_session_token=settings.get('AWS_SESSION_TOKEN') or None,region_name=settings.get('AWS_DEFAULT_REGION','us-east-2'))
s3=session.client('s3')
manifest=None;gold_error=None
try:
 blob=s3.get_object(Bucket='cc3105-au-869227452861-us-east-2-an',Key='cc3105-equipo5/api/current.json')['Body'].read()
 manifest=json.loads(blob)
 if manifest.get('version')!=1:raise ValueError('Oro no tiene una publicación válida')
except Exception as exc:
 gold_error=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
 if not ALLOW_UNAVAILABLE:raise RuntimeError('No se pudo leer Oro: '+gold_error) from None
 print(json.dumps({'oro_no_disponible':gold_error,'servicio':'Arranca con 503 hasta habilitar lectura Oro'}),flush=True)
# Conservar la interfaz autorizada en el servidor; no tocar firewall ni SSH.
settings=parse_env(env.read_text())
bind_host=REQUESTED_BIND or settings.get('API_BIND_HOST','127.0.0.1')
if bind_host not in ('127.0.0.1','0.0.0.0'):raise ValueError('Interfaz de publicación no permitida')
if bind_host=='0.0.0.0' and LOCAL_PORT!=8000:raise ValueError('Puerto público no autorizado')
sock=socket.socket()
try:sock.bind((bind_host,LOCAL_PORT))
except OSError:
 existing=subprocess.run(['docker','ps','--filter','label=com.docker.compose.project=cc3105-03-equipo05','--format','{{.Ports}}'],capture_output=True,text=True,check=True).stdout
 if not any(host+':'+str(LOCAL_PORT)+'->' in existing for host in ('127.0.0.1','0.0.0.0')):raise RuntimeError('Puerto ocupado por otro servicio; no se reemplaza')
finally:sock.close()
compose=app/'api/compose.yaml'
write_env_atomic(env,update_env(env.read_text(),{'API_BIND_HOST':bind_host,'API_PORT':str(LOCAL_PORT)}))
subprocess.run(['docker','compose','--env-file',str(env),'-p','cc3105-03-equipo05','-f',str(compose),'up','--build','-d'],cwd=app,check=True)
print(json.dumps({'directorio':str(app),'url_local':'http://127.0.0.1:'+str(LOCAL_PORT),'interfaz_publicacion':bind_host,'origen':'S3_ORO','release':manifest['release'] if manifest else None,'oro_error':gold_error}))
'''.replace('ARCHIVE_NAME',repr(Path(remote_archive).name)).replace('LOCAL_PORT',str(a.port)).replace('ALLOW_UNAVAILABLE',repr(a.allow_unavailable_gold)).replace('REQUESTED_BIND',repr(a.bind_host)).replace('IMPORT_SERVER_CREDENTIALS',repr(a.import_server_credentials))
    script=(ROOT/'scripts/server_env.py').read_text()+'\n'+script
    subprocess.run(['ssh',*flags,address,'python3 -'],input=script,text=True,check=True)

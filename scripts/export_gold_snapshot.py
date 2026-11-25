"""Descarga una copia explícita de Oro para pruebas y demo sin conexión; no sustituye el acceso AWS de la API."""
import base64,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.databricks_client import api
PREFIX='s3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/'

def read_object(path):
    if not path.startswith(PREFIX) or '..' in path.split('/'):raise ValueError('Objeto fuera de Oro')
    query="SELECT base64(content) FROM read_files('"+path.replace("'","''")+"', format => 'binaryFile')"
    response=api('post','/api/2.0/sql/statements',{'warehouse_id':'4b28a3706d123886','statement':query,'wait_timeout':'10s','on_wait_timeout':'CONTINUE','row_limit':1})
    deadline=time.monotonic()+240
    while response['status']['state'] in ('PENDING','RUNNING'):
        if time.monotonic()>deadline:raise TimeoutError('La lectura SQL no terminó')
        time.sleep(3);response=api('get','/api/2.0/sql/statements/'+response['statement_id'])
    if response['status']['state']!='SUCCEEDED':raise RuntimeError(str(response['status']))
    rows=response.get('result',{}).get('data_array',[])
    if len(rows)!=1:raise ValueError('Se esperaba exactamente un archivo')
    return base64.b64decode(''.join(rows[0][0].split()),validate=True)

if __name__=='__main__':
    root=ROOT/'output/api_oro_real';root.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(read_object(PREFIX+'current.json'))
    (root/'manifest_s3_original.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    release=manifest['release'];directory=root/'releases'/release;directory.mkdir(parents=True,exist_ok=True)
    for name,paths in manifest['tablas'].items():
        local=[]
        for i,path in enumerate(paths):
            if not path.startswith(PREFIX+'releases/'+release+'/'):raise ValueError('Versiones mezcladas')
            dest=directory/f'{name}_{i}.parquet';dest.write_bytes(read_object(path));local.append(str(dest.relative_to(root)))
        manifest['tablas'][name]=local
    manifest['origen']='COPIA_LOCAL_DE_ORO_S3';manifest['source_manifest']=PREFIX+'current.json'
    (root/'current.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({'snapshot':str(root/'current.json'),'release':release,'origen':manifest['origen']}))

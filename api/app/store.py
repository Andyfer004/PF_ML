"""Lector de publicaciones Parquet de Oro, con versiones inmutables y lectura AWS."""
import io,json,re,threading,time
from pathlib import Path
from urllib.parse import urlparse
import pyarrow.parquet as pq

GOLD_PREFIX='s3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/'

class GoldStore:
    def __init__(self,manifest,ttl=30,client=None):
        self.location=str(manifest);self.ttl=ttl;self.client=client
        self.lock=threading.Lock();self.loaded=0;self.tables={};self.manifest={}
        if self.location.startswith('s3://') and not self.location.startswith(GOLD_PREFIX):
            raise ValueError('La API solo puede leer el prefijo Oro del equipo 5')

    def _read(self,path):
        if self.location.startswith('s3://'):
            if not path.startswith(GOLD_PREFIX):raise ValueError('Objeto fuera de Oro')
            if self.client is None:
                import boto3
                from botocore.config import Config
                self.client=boto3.client('s3',region_name='us-east-2',config=Config(connect_timeout=5,read_timeout=15,retries={'max_attempts':2}))
            u=urlparse(path)
            return self.client.get_object(Bucket=u.netloc,Key=u.path.lstrip('/'))['Body'].read()
        root=Path(self.location).resolve().parent
        target=(root/path).resolve()
        if not target.is_relative_to(root):raise ValueError('Objeto fuera de la publicación local')
        return target.read_bytes()

    def snapshot(self):
        with self.lock:
            if self.tables and time.monotonic()-self.loaded<self.ttl:return self.manifest,self.tables
            if self.location.startswith('s3://'):raw=self._read(self.location)
            else:raw=Path(self.location).read_bytes()
            manifest=json.loads(raw)
            if manifest.get('version')!=1 or not re.fullmatch(r'[a-f0-9]{32}',manifest.get('release','')):raise ValueError('Manifiesto inválido')
            required=('precio_semanal','variacion_semanal','predicciones','metricas_modelo')
            optional=('predicciones_historicas',) if 'predicciones_historicas' in manifest['tablas'] else ()
            tables={}
            for name in required+optional:
                files=manifest['tablas'].get(name,[])
                if not files:raise ValueError('Publicación incompleta: '+name)
                rows=[]
                for path in files:
                    if self.location.startswith('s3://') and not path.startswith(GOLD_PREFIX+'releases/'+manifest['release']+'/'):
                        raise ValueError('El archivo pertenece a otra publicación')
                    rows.extend(pq.read_table(io.BytesIO(self._read(path))).to_pylist())
                tables[name]=rows
            self.manifest,self.tables=manifest,tables;self.loaded=time.monotonic()
            return manifest,tables

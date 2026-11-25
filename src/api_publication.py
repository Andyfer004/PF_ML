"""Publicación inmutable de Oro en el prefijo AWS autorizado temporalmente."""
import json
import uuid

API_ROOT = 's3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/'
TABLES = ('precio_semanal', 'variacion_semanal', 'predicciones', 'predicciones_historicas', 'metricas_modelo')


def publish_api(spark, dbutils, cfg, cutoff, blocked=None):
    root = cfg.get('api_root', API_ROOT)
    if root != API_ROOT or cfg['catalog'] != 'lakehouse_equipo5':
        raise ValueError('Publicación fuera de los recursos autorizados temporalmente')
    release = uuid.uuid4().hex
    quality = spark.sql(f"SELECT estado FROM {cfg['catalog']}.silver.calidad_extraccion ORDER BY fecha_corte DESC LIMIT 1").first()['estado']
    manifest = {'version': 1, 'release': release, 'fecha_corte': str(cutoff),
                'fuente_default': cfg['fuente_modelo'], 'tablas': {},
                'validacion_ocr': quality, 'equipo_proyecto': int(cfg['equipo']),
                'identidad_aws_temporal': 'cc3105-equipo'+str(int(cfg['equipo_recursos']))}
    if blocked is not None:
        manifest['predicciones_bloqueadas'] = blocked
    for name in TABLES:
        path = root + 'releases/' + release + '/' + name + '/'
        spark.table(cfg['catalog'] + '.gold.' + name).coalesce(1).write.mode('error').parquet(path)
        manifest['tablas'][name] = [f.path for f in dbutils.fs.ls(path) if f.name.endswith('.parquet')]
        if not manifest['tablas'][name]:
            raise ValueError('Exportación vacía: ' + name)
    # El puntero solo cambia una vez que todos los Parquet están completos.
    dbutils.fs.put(root + 'releases/' + release + '/manifest.json', json.dumps(manifest, ensure_ascii=False), False)
    dbutils.fs.put(root + 'current.json', json.dumps(manifest, ensure_ascii=False), True)
    return {'api_manifest': root + 'current.json', 'release': release}

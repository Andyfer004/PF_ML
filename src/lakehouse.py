"""Configuración y escrituras Delta limitadas al catálogo y prefijos del equipo."""
import hashlib
import json
import re
import sys
from importlib import metadata
from datetime import date
from pathlib import Path

DEFAULTS = {
    'equipo': '03', 'equipo_recursos': '05', 'compute_mode': 'serverless',
    'catalog': 'lakehouse_equipo5', 'workspace_path': '/Workspace/Users/fue22944@uvg.edu.gt/PF-ML',
    'source_path': 's3://cc3105-raw-869227452861-us-east-2-an/img/',
    'source_root': 's3://cc3105-raw-869227452861-us-east-2-an/img/',
    'bronze_root': 's3://cc3105-cusn-869227452861-us-east-2-an/equipo-05/',
    'silver_root': 's3://cc3105-ag-869227452861-us-east-2-an/equipo-05/',
    'gold_root': 's3://cc3105-au-869227452861-us-east-2-an/equipo-05/',
    'api_root': 's3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/',
    'fecha_corte': '', 'umbral_q': '0.10', 'fuente_modelo': 'mem', 'max_photos': '500',
}
TABLES = {'bronze': {'fotos_precios', 'mem_archivos'},
          'silver': {'precios', 'precios_rejected', 'precios_mem', 'ocr_cache', 'calidad_extraccion'},
          'gold': {'precio_semanal', 'variacion_semanal', 'features_modelo', 'predicciones', 'predicciones_historicas', 'metricas_modelo'}}


def config(dbutils):
    from zoneinfo import ZoneInfo
    from datetime import datetime
    values = {}
    for key, default in DEFAULTS.items():
        if key == 'fecha_corte': default = datetime.now(ZoneInfo('America/Guatemala')).date().isoformat()
        dbutils.widgets.text(key, default)
        values[key] = dbutils.widgets.get(key).strip() or default
    validate_config(values)
    return values


def validate_config(values):
    validate_identity(values)
    if values['catalog'] != 'lakehouse_equipo5': raise ValueError('Catálogo ajeno al equipo')
    if values.get('api_root', DEFAULTS['api_root']) != DEFAULTS['api_root']: raise ValueError('Prefijo API no autorizado')
    for key in ('bronze_root', 'silver_root', 'gold_root', 'source_path'):
        if not values[key].startswith(DEFAULTS[key]) or '..' in values[key].split('/'):
            raise ValueError('Ruta fuera del prefijo autorizado: '+key)
    if values['fuente_modelo'] not in ('mem', 'fotos'): raise ValueError('Fuente inválida')
    if not 0 < float(values['umbral_q']) <= 5: raise ValueError('Umbral inválido')
    if not 1 <= int(values['max_photos']) <= 500: raise ValueError('Límite de fotografías inválido')
    date.fromisoformat(values['fecha_corte'])
    return values


def validate_identity(values):
    """Parámetros del proyecto dentro del alcance temporal autorizado."""
    for key in ('equipo','equipo_recursos'):
        value=str(values.get(key,DEFAULTS[key])).zfill(2)
        if value!=DEFAULTS[key]:raise ValueError('Identidad fuera del proyecto autorizado: '+key)
        values[key]=value
    if values.get('compute_mode','serverless') not in ('serverless','classic'):
        raise ValueError('Cómputo debe ser serverless o classic')
    if values.get('source_root',DEFAULTS['source_root'])!=DEFAULTS['source_root']:
        raise ValueError('Raíz de fotos fuera de la ubicación compartida autorizada')
    return values


def compute_evidence(spark,mode):
    libraries={}
    for name in ('pillow-heif','rapidocr-onnxruntime','opencv-python','openpyxl','scikit-learn','pandas','scipy','mlflow','mlflow-skinny'):
        try:libraries[name]=metadata.version(name)
        except metadata.PackageNotFoundError:continue
    try:version=spark.version
    except Exception:version=None
    return {'modo_configurado':mode,'python':sys.version.split()[0],
            'spark':version,'librerias_instaladas':libraries,
            'infraestructura':('Runtime, nodos, workers y terminación gestionados por Databricks; no equivalen a un cluster clásico configurable'
                               if mode=='serverless' else 'Consultar la configuración y cluster_id de la ejecución clásica'),
            'autorizacion_docente_serverless':'PENDIENTE' if mode=='serverless' else 'NO_APLICA'}


def code_signature(base):
    names = ('src/lcd_ocr.py','src/price_quality.py','src/generic_ocr.py','src/photo_metadata.py','data/ocr_layout_templates.json','data/ocr_review_flags.csv')
    return hashlib.sha256(b''.join((Path(base)/n).read_bytes() for n in names)).hexdigest()


def frame_from_pandas(spark, frame):
    import pandas as pd
    from pyspark.sql.types import StructType,StructField,StringType,DoubleType,LongType,BooleanType,DateType
    types=[]
    for col in frame:
        dtype=frame[col].dtype
        kind=(DateType() if pd.api.types.is_datetime64_any_dtype(dtype) else
              BooleanType() if pd.api.types.is_bool_dtype(dtype) else
              LongType() if pd.api.types.is_integer_dtype(dtype) else
              DoubleType() if pd.api.types.is_numeric_dtype(dtype) else StringType())
        types.append(StructField(col,kind,True))
    rows=json.loads(frame.to_json(orient='records',date_format='iso'))
    for row in rows:
        for field in types:
            value=row[field.name]
            if value is None:continue
            if isinstance(field.dataType,DateType):row[field.name]=date.fromisoformat(value[:10])
            elif isinstance(field.dataType,DoubleType):row[field.name]=float(value)
            elif isinstance(field.dataType,LongType):row[field.name]=int(value)
            elif isinstance(field.dataType,StringType) and not isinstance(value,str):row[field.name]=json.dumps(value,ensure_ascii=False)
    return spark.createDataFrame(rows,StructType(types))


def publish(spark, cfg, layer, name, frame, keys, sync=True, comment=''):
    """MERGE de una tabla propia; verifica ubicación antes de modificarla."""
    from delta.tables import DeltaTable
    if name not in TABLES.get(layer,set()): raise ValueError('Tabla fuera del contrato')
    full=f"{cfg['catalog']}.{layer}.{name}"
    quoted='.'.join(f'`{p}`' for p in full.split('.'))
    location=cfg[layer+'_root'].rstrip('/')+'/'+name+'/'
    if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',c) for c in frame.columns):raise ValueError('Columna inválida')
    if frame.groupBy(*keys).count().filter('count > 1').limit(1).count():raise ValueError('Llave duplicada: '+full)
    if spark.catalog.tableExists(full):
        detail=spark.sql('DESCRIBE DETAIL '+quoted).first()
        if detail['location'].rstrip('/')!=location.rstrip('/'):raise ValueError('La tabla apunta a otra ubicación: '+full)
        operation=DeltaTable.forName(spark,full).alias('t').merge(frame.alias('s'),' AND '.join(f't.`{k}` <=> s.`{k}`' for k in keys)).whenMatchedUpdateAll().whenNotMatchedInsertAll()
        if sync:operation=operation.whenNotMatchedBySourceDelete()
        operation.execute()
    else:
        view='_pf_publicacion_'+layer+'_'+name
        frame.createOrReplaceTempView(view)
        spark.sql(f"CREATE TABLE {quoted} USING DELTA LOCATION '{location}' AS SELECT * FROM `{view}`")
        spark.catalog.dropTempView(view)
    text=(comment or name.replace('_',' ')).replace("'","''")
    spark.sql(f"COMMENT ON TABLE {quoted} IS '{text}'")
    descriptions={'semana':'Inicio de semana de martes a lunes','fecha':'Fecha observada del precio','combustible':'super, regular o diesel','fuente':'Cohorte de origen, sin mezclar fotografías y MEM','precio_q_galon':'Precio en quetzales por galón','precio_promedio':'Promedio semanal en quetzales por galón','precio_minimo':'Mínimo semanal en quetzales por galón','precio_maximo':'Máximo semanal en quetzales por galón','direccion':'Cambio semanal: sube, baja o se_mantiene','probabilidad':'Probabilidad de la clase elegida, sin calibración adicional','prediccion':'Dirección estimada para la semana objetivo','direccion_real':'Dirección observada cuando la semana objetivo ya cerró','estado_calidad':'Estado de validación y procedencia de los datos','foto_origen':'Ruta de trazabilidad a la imagen original conservada en Bronce','ubicacion':'Ubicación visible; no_identificada si no se puede leer','modalidad':'Modalidad visible; no_identificada si no se puede leer'}
    descriptions.update({
      'fecha_corte_simulada':'Final del lunes anterior a la semana objetivo en una evaluación histórica; no es la fecha real de ejecución',
      'entrenamiento_hasta':'Último día de etiquetas usadas por el modelo evaluado, anterior a todas las semanas de prueba',
      'generado_el':'Instante real de ejecución con zona horaria; no se retrofecha la generación',
      'modo':'evaluacion_historica: reconstrucción de prueba reservada, no pronóstico vigente',
      'acierto':'La predicción histórica coincide con la dirección observada de la semana objetivo',
      'baseline_acierto':'La última dirección conocida coincide con la dirección real de la semana objetivo',
      'precio_semana_base':'Promedio observado de la semana de entrada, en Q por galón',
      'precio_semana_objetivo':'Promedio observado posteriormente para evaluar la semana objetivo, en Q por galón',
      'variacion_real_q':'Precio de la semana objetivo menos precio de la semana base, en Q por galón',
      'precio_anterior':'Precio promedio de exactamente siete días antes, en Q por galón; null si falta esa semana',
      'cambio_1w':'Precio promedio menos precio de la semana anterior exacta, en Q por galón',
      'variacion_pct':'Cien por cambio semanal dividido entre precio anterior',
      'cambio_ultima_observacion':'Diferencia contra la última observación disponible, aunque exista un hueco de semanas',
      'semanas_desde_ultima_observacion':'Distancia en semanas a la observación anterior disponible',
      'mes_sin':'Seno del mes multiplicado por dos pi y dividido entre doce',
      'mes_cos':'Coseno del mes multiplicado por dos pi y dividido entre doce',
      'precio_siguiente':'Precio de la semana objetivo; solo etiqueta y evaluación, nunca variable de entrada',
      'semana_objetivo':'Martes de la semana cuya dirección se predice; incorpora el horizonte del modelo',
      'objetivo':'Dirección real de la semana objetivo frente a su semana anterior exacta',
      'baseline':'Última dirección conocida a la fecha de las variables de entrada',
      'semana_cerrada':'True si la semana terminó antes o en la fecha de corte',
      'observaciones':'Número de observaciones deduplicadas en la semana y combustible',
      'ubicaciones':'Número de ubicaciones distintas presentes en la semana',
      'fecha_corte':'Fecha límite de observaciones y etiquetas disponibles en America/Guatemala',
      'fecha_emision':'Fecha del pronóstico en America/Guatemala',
      'semana_datos':'Martes de la semana que proporciona las variables al modelo',
      'semana_base_cerrada':'Indica si la semana de datos terminó a la fecha de emisión',
      'observaciones_semana_base':'Cantidad de observaciones de la semana usada como entrada',
      'horizonte_semanas':'Semanas entre la semana de datos y la semana objetivo; uno o dos',
      'antiguedad_datos_dias':'Días entre la emisión y el martes de la semana de datos',
      'modelo':'Clasificador elegido mediante macro F1 de validación temporal',
      'accuracy':'Fracción de direcciones acertadas en la partición temporal de prueba',
      'macro_f1':'F1 promedio de baja, se_mantiene y sube en prueba, incluyendo clases ausentes',
      'baseline_accuracy':'Exactitud de repetir la última dirección conocida en la misma prueba',
      'baseline_macro_f1':'Macro F1 del baseline en la misma partición de prueba',
      'n_prueba':'Número de pares semana objetivo y combustible evaluados',
      'mlflow_run_id':'Identificador del experimento con modelo evaluado y reajuste de producción',
      'detalle_json':'Métricas, variables, particiones y procedencia completas en JSON'
    })
    if layer=='gold':
        for col in frame.columns:
            desc=descriptions.get(col,col.replace('_',' ').capitalize()).replace("'","''")
            spark.sql(f"ALTER TABLE {quoted} ALTER COLUMN `{col}` COMMENT '{desc}'")
    return {'tabla':full,'filas':spark.table(full).count(),'ubicacion':location}

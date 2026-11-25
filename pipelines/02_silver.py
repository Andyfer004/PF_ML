# Databricks notebook source
spark.range(1).count()
# COMMAND ----------
# MAGIC %pip install pillow-heif==1.1.1 rapidocr-onnxruntime==1.4.4 opencv-python==4.11.0.86 openpyxl==3.1.5
# COMMAND ----------
dbutils.library.restartPython()
# COMMAND ----------
import csv,hashlib,io,json,sys,tempfile
from pathlib import Path
from datetime import date
from decimal import Decimal
import pandas as pd
from pyspark.sql import functions as F

dbutils.widgets.text('workspace_path','/Workspace/Users/fue22944@uvg.edu.gt/PF-ML')
base=Path(dbutils.widgets.get('workspace_path'));sys.path.insert(0,str(base))
from src.lakehouse import config,publish,code_signature,frame_from_pandas,compute_evidence
from src.price_quality import quarantine_review_flags
from src.prepare_mem import normalize
cfg=config(dbutils);cutoff=date.fromisoformat(cfg['fecha_corte']);signature=code_signature(base)
bronze=spark.table(cfg['catalog']+'.bronze.fotos_precios').orderBy('path')
count=bronze.count()
if count>int(cfg['max_photos']):raise ValueError('Particionar el lote: excede max_photos')
if (bronze.agg(F.sum('length')).first()[0] or 0)>256*1024*1024:raise ValueError('Particionar: lote mayor de 256 MiB')
cache={}
cache_table=cfg['catalog']+'.silver.ocr_cache'
if spark.catalog.tableExists(cache_table):
    for r in spark.table(cache_table).collect():cache[(r.foto_origen,r.sha256_imagen,r.firma_codigo)]=r.resultado_json
seed=base/'ocr_seed.json'
if seed.exists():
    data=json.loads(seed.read_text())
    if data.get('firma_codigo')==signature:
        for r in data['fotos']:
            if r.get('sha256_imagen'):cache.setdefault((r['foto_origen'],r['sha256_imagen'],signature),json.dumps(r,ensure_ascii=False))
with (base/'data/ocr_review_flags.csv').open(newline='') as stream:
    flags={(r['foto_origen'],r['combustible']):r['motivo'] for r in csv.DictReader(stream)}
all_rows=[];cache_rows=[];errors=[];reused=0;source_photos=[]
with tempfile.TemporaryDirectory(prefix='equipo05_ocr_') as directory:
    extractor=None
    for record in bronze.select('path','content','_content_sha256').collect():
        source_photos.append(record.path)
        key=(record.path,record._content_sha256,signature)
        try:
            if key in cache:
                result=json.loads(cache[key]);reused+=1
            else:
                if extractor is None:
                    from src.lcd_ocr import LCDExtractor
                    for template in json.loads((base/'data/ocr_layout_templates.json').read_text()):
                        origin=cfg['source_root'].rstrip('/')+'/'+template['archivo']
                        blob=spark.read.format('binaryFile').load(origin).select('content').first().content
                        dest=Path(directory)/template['archivo'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(bytes(blob))
                    extractor=LCDExtractor(tesseract=False,template_root=directory,template_config=base/'data/ocr_layout_templates.json')
                result=extractor.extract(io.BytesIO(bytes(record.content)),record.path)
            cache_rows.append((record.path,record._content_sha256,signature,json.dumps(result,ensure_ascii=False)))
            all_rows.extend(result['resultados'])
        except Exception as exc:
            errors.append({'foto_origen':record.path,'error':str(exc)[:1000]})
            all_rows.append({'foto_origen':record.path,'combustible':'no_identificado','fecha':None,'precio_q_galon':None,'motivos_revision':['ERROR_EXTRACCION']})
cache_df=spark.createDataFrame(cache_rows,'foto_origen string, sha256_imagen string, firma_codigo string, resultado_json string')
summary={'fotos':count,'cache_reutilizada':reused,'errores':errors,'tablas':[]}
summary.update(equipo=cfg['equipo'],equipo_recursos=cfg['equipo_recursos'],computo=compute_evidence(spark,cfg['compute_mode']))
summary['tablas'].append(publish(spark,cfg,'silver','ocr_cache',cache_df,['foto_origen'],comment='Caché OCR por imagen, hash binario y firma de código'))
from src.silver import clean_photos,extraction_summary,KEY,COLUMNS
references_path=base/'referencias_ocr_revisadas.json'
if references_path.exists():references=json.loads(references_path.read_text())
elif (base/'data/evaluacion_ocr_confirmada.csv').exists():
    with (base/'data/evaluacion_ocr_confirmada.csv').open(newline='') as stream:references=list(csv.DictReader(stream))
else:references=[]
accepted,rejected=clean_photos(all_rows,flags,cfg['fecha_corte'],references)
summary['resumen_extraccion']=extraction_summary(source_photos,accepted,rejected)
print(json.dumps(summary['resumen_extraccion'],ensure_ascii=False,indent=2))
display(spark.createDataFrame(
        [(key,value) for key,value in summary['resumen_extraccion'].items() if key!='rechazos_por_motivo'],
        'indicador string, cantidad long'))
display(spark.createDataFrame(
    [(r['motivo_rechazo'],r['registros'],r['fotos']) for r in summary['resumen_extraccion']['rechazos_por_motivo']],
    'motivo_rechazo string, registros long, fotos long'))
key=KEY
for name,data,keys in [('precios',accepted,key),('precios_rejected',rejected,['foto_origen','combustible'])]:
    schema='fecha date, combustible string, precio_q_galon decimal(10,2), modalidad string, ubicacion string, foto_origen string, fuente string, estado_calidad string, motivo_rechazo string'
    typed=[]
    for row in data.to_dict('records'):
        row['fecha']=date.fromisoformat(row['fecha']) if row['fecha'] else None
        row['precio_q_galon']=Decimal(row['precio_q_galon']) if row['precio_q_galon'] else None
        typed.append(tuple(row[c] for c in COLUMNS))
    sdf=spark.createDataFrame(typed,schema)
    summary['tablas'].append(publish(spark,cfg,'silver',name,sdf,keys,comment='Fotografías del curso; candidatos OCR y rechazo conservador, sin completar valores faltantes'))
# El histórico oficial tiene una tabla separada; se normaliza desde el binario de Bronce.
mem=spark.table(cfg['catalog']+'.bronze.mem_archivos').orderBy(F.desc('_ingestion_timestamp')).first()
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'mem.xlsx';path.write_bytes(bytes(mem.content));mem_rows=normalize(path,as_of=cfg['fecha_corte'])
mem_frame=pd.DataFrame(mem_rows)
mem_key=['fecha','combustible','ubicacion','modalidad']
if (mem_frame.groupby(mem_key).precio_q_galon.nunique()>1).any():raise ValueError('MEM tiene precios contradictorios para la misma llave')
summary['mem_duplicados_identicos']=int(mem_frame.duplicated(mem_key).sum())
mem_frame=mem_frame.drop_duplicates(mem_key).copy()
mem_frame['fecha']=pd.to_datetime(mem_frame['fecha']);mem_frame['estado_calidad']='FUENTE_OFICIAL_RETROSPECTIVA'
summary['tablas'].append(publish(spark,cfg,'silver','precios_mem',frame_from_pandas(spark,mem_frame),['fecha','combustible','ubicacion','modalidad'],comment='MEM ciudad capital, separado de precios de estaciones fotografiadas'))
from src.ocr_evaluation import evaluate
validation=evaluate({'resultados':all_rows},references)
quality=pd.DataFrame([{'fecha_corte':cfg['fecha_corte'],'fotos_procesadas':count,'precios_aceptados':len(accepted),'precios_rechazados':len(rejected),'fotos_revisadas_humanas':validation['fotos_con_referencia_humana'],'estado':'MUESTRA_HUMANA_20_FOTOS_COMPLETA' if validation['cumple_minimo_20_fotos'] else 'PENDIENTE_REVISION_20_FOTOS','firma_codigo':signature}])
for field in ('exactitud_incluyendo_omisiones','cobertura','precision_sobre_extraidos'):
    quality[field]=pd.Series([validation[field]],dtype='float64')
summary['validacion_humana']=validation
print('Revisión humana: '+json.dumps(validation,ensure_ascii=False))
summary['tablas'].append(publish(spark,cfg,'silver','calidad_extraccion',frame_from_pandas(spark,quality),['fecha_corte'],sync=False))
summary.update(aceptados=len(accepted),rechazados=len(rejected),estado_validacion_humana=quality.iloc[0]['estado'])
(base/'resultado_silver.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
dbutils.notebook.exit(json.dumps(summary,ensure_ascii=False))

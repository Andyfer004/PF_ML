# Databricks notebook source
spark.range(1).count()
# COMMAND ----------
# MAGIC %pip install scikit-learn==1.6.1 pandas==2.3.3 scipy==1.15.3
# COMMAND ----------
dbutils.library.restartPython()
# COMMAND ----------
import json,sys,tempfile,uuid
from pathlib import Path
from datetime import date,datetime
from zoneinfo import ZoneInfo
import pandas as pd
import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature
from pyspark.sql import functions as F

dbutils.widgets.text('workspace_path','/Workspace/Users/fue22944@uvg.edu.gt/PF-ML')
base=Path(dbutils.widgets.get('workspace_path'));sys.path.insert(0,str(base))
from src.lakehouse import config,publish,frame_from_pandas,compute_evidence
from src.predictor import train_predictor,forecast,build_tables,FEATURES,historical_predictions
cfg=config(dbutils);cutoff=cfg['fecha_corte'];threshold=float(cfg['umbral_q'])
mlflow.set_tracking_uri('databricks');mlflow.set_registry_uri('databricks-uc')
summary={'fecha_corte':cutoff,'fuente_modelo':cfg['fuente_modelo'],'tablas':[],'modelos':{},'predicciones_bloqueadas':{}}
summary.update(equipo=cfg['equipo'],equipo_recursos=cfg['equipo_recursos'],computo=compute_evidence(spark,cfg['compute_mode']))
frames={};models={};reports={};all_predictions=[];metric_rows=[];all_historical=[]
for source,table in [('fotos','precios'),('mem','precios_mem')]:
    observations=[r.asDict() for r in spark.table(cfg['catalog']+'.silver.'+table).filter(F.col('fecha')<=F.lit(cutoff)).collect()]
    if not observations:
        summary['modelos'][source]={'estado':'SIN_DATOS'};continue
    # La pregunta del proyecto es siempre la dirección de la semana siguiente.
    horizon=1
    weekly,features,supervised=build_tables(observations,threshold,cutoff,horizon_weeks=horizon)
    frames[source]={'precio_semanal':weekly,'features_modelo':features}
    try:
        model,report,tables=train_predictor(observations,threshold,cutoff,horizon_weeks=horizon)
        predictions,blocked=forecast(model,tables['features_modelo'],cutoff)
    except ValueError as exc:
        summary['modelos'][source]={'estado':'HISTORIA_INSUFICIENTE','detalle':str(exc)}
        if source==cfg['fuente_modelo']:raise
        continue
    quality='FUENTE_OFICIAL_RETROSPECTIVA' if source=='mem' else 'OCR_CANDIDATO_PENDIENTE_VALIDACION_HUMANA'
    report.update(fuente=source,estado_calidad=quality,fecha_corte=cutoff,predicciones=predictions,predicciones_bloqueadas=blocked)
    historical=historical_predictions(model,report,tables,datetime.now(ZoneInfo('America/Guatemala')).isoformat())
    mlflow.set_experiment(cfg['workspace_path'].removeprefix('/Workspace')+'/experimento_predictor_'+source)
    with mlflow.start_run(run_name='pipeline_'+source+'_'+cutoff) as run:
        mlflow.log_params({'fuente':source,'modelo':report['modelo'],'umbral_q':threshold,'fecha_corte':cutoff,'estado_calidad':quality,'horizonte_semanas':horizon})
        mlflow.log_metrics({'test_accuracy':report['modelo_test']['accuracy'],'test_macro_f1':report['modelo_test']['macro_f1'],'baseline_accuracy':report['baseline_test']['accuracy'],'baseline_macro_f1':report['baseline_test']['macro_f1']})
        mlflow.sklearn.log_model(model.evaluation_model_,artifact_path='modelo_evaluado',signature=infer_signature(tables['evaluacion_temporal'][FEATURES],tables['evaluacion_temporal']['prediccion']))
        mlflow.sklearn.log_model(model,artifact_path='modelo_produccion',signature=infer_signature(tables['features_modelo'][FEATURES],model.predict(tables['features_modelo'][FEATURES])))
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'metricas.json';p.write_text(json.dumps(report,ensure_ascii=False,indent=2));mlflow.log_artifact(str(p))
            p=Path(directory)/'predicciones_historicas.csv';pd.DataFrame(historical).to_csv(p,index=False);mlflow.log_artifact(str(p))
            for name,frame in tables.items():
                p=Path(directory)/(name+'.csv');frame.to_csv(p,index=False);mlflow.log_artifact(str(p))
        report['mlflow_run_id']=run.info.run_id
    models[source]=model;reports[source]=report
    summary['modelos'][source]={'estado':'ENTRENADO','modelo':report['modelo'],'test':report['modelo_test'],'baseline':report['baseline_test'],'mlflow_run_id':report['mlflow_run_id'],'horizonte_semanas':horizon}
    summary['predicciones_bloqueadas'][source]=blocked
    summary.setdefault('evaluacion_historica',{})[source]={'registros':len(historical),'desde':min(r['semana'] for r in historical),'hasta':max(r['semana'] for r in historical),'mlflow_run_id':report['mlflow_run_id']}
    for row in historical:
        row.update(fuente=source,mlflow_run_id=report['mlflow_run_id']);all_historical.append(row)
    for prediction in predictions:
        prediction.update(fuente=source,estado_calidad=quality,mlflow_run_id=report['mlflow_run_id']);all_predictions.append(prediction)
    metric_rows.append({'fuente':source,'fecha_corte':cutoff,'modelo':report['modelo'],'accuracy':report['modelo_test']['accuracy'],'macro_f1':report['modelo_test']['macro_f1'],'baseline_accuracy':report['baseline_test']['accuracy'],'baseline_macro_f1':report['baseline_test']['macro_f1'],'n_prueba':report['modelo_test']['n'],'estado_calidad':quality,'mlflow_run_id':report['mlflow_run_id'],'horizonte_semanas':horizon,'detalle_json':json.dumps(report,ensure_ascii=False)})

for name in ('precio_semanal','features_modelo','variacion_semanal'):
    pieces=[]
    for source,tables in frames.items():
        frame=tables['precio_semanal' if name=='precio_semanal' else 'features_modelo'].copy()
        if name=='variacion_semanal':frame=frame[['semana','combustible','precio_promedio','precio_anterior','cambio_1w','variacion_pct','direccion','semana_cerrada']]
        frame['fuente']=source;frame['estado_calidad']='FUENTE_OFICIAL_RETROSPECTIVA' if source=='mem' else 'OCR_CANDIDATO_PENDIENTE_VALIDACION_HUMANA'
        pieces.append(frame)
    combined=pd.concat(pieces,ignore_index=True)
    summary['tablas'].append(publish(spark,cfg,'gold',name,frame_from_pandas(spark,combined),['fuente','semana','combustible'],comment='Semanas martes a lunes; fuentes separadas; precios en Q/galón; sin rellenar semanas faltantes'))
pred_columns=['combustible','semana','semana_datos','prediccion','probabilidad','direccion_real','fecha_emision','semana_base_cerrada','observaciones_semana_base','fuente','estado_calidad','mlflow_run_id','horizonte_semanas','antiguedad_datos_dias']
pred=pd.DataFrame(all_predictions,columns=pred_columns)
for c in ('semana','semana_datos','fecha_emision'):pred[c]=pd.to_datetime(pred[c])
pred['probabilidad']=pd.to_numeric(pred['probabilidad']).astype('float64');pred['observaciones_semana_base']=pd.to_numeric(pred['observaciones_semana_base']).astype('int64');pred['semana_base_cerrada']=pred['semana_base_cerrada'].astype(bool)
summary['tablas'].append(publish(spark,cfg,'gold','predicciones',frame_from_pandas(spark,pred),['fuente','semana','combustible'],sync=False,comment='Pronósticos emitidos antes de empezar su semana; no se generan pronósticos vencidos'))
# Completar la dirección real únicamente con semanas cerradas; conservar predicciones históricas.
for source,tables in frames.items():
    actual=tables['features_modelo'].loc[lambda x:x.semana_cerrada,['semana','combustible','direccion']].copy();actual['fuente']=source
    actual=frame_from_pandas(spark,actual);actual.createOrReplaceTempView('_direccion_real')
    spark.sql(f"MERGE INTO {cfg['catalog']}.gold.predicciones t USING _direccion_real s ON t.fuente=s.fuente AND t.semana=s.semana AND t.combustible=s.combustible WHEN MATCHED AND s.direccion IS NOT NULL THEN UPDATE SET t.direccion_real=s.direccion")
metric_frame=pd.DataFrame(metric_rows);metric_frame['fecha_corte']=pd.to_datetime(metric_frame['fecha_corte'])
summary['tablas'].append(publish(spark,cfg,'gold','metricas_modelo',frame_from_pandas(spark,metric_frame),['fuente','fecha_corte'],sync=False,comment='Evaluación temporal fuera de entrenamiento y baseline; no garantiza acierto futuro'))
historical_frame=pd.DataFrame(all_historical)
for column in ('semana','semana_datos','fecha_corte_simulada','entrenamiento_hasta'):
    historical_frame[column]=pd.to_datetime(historical_frame[column])
summary['tablas'].append(publish(spark,cfg,'gold','predicciones_historicas',frame_from_pandas(spark,historical_frame),['fuente','semana','combustible'],comment='Prueba temporal reservada con modelo entrenado antes del bloque; fecha de corte simulada y generación real separadas'))
# Publicación explícita en el prefijo de la identidad AWS temporal autorizada.
from src.api_publication import publish_api
summary.update(publish_api(spark,dbutils,cfg,cutoff,summary['predicciones_bloqueadas']))
(base/'resultado_gold.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
dbutils.notebook.exit(json.dumps(summary,ensure_ascii=False))

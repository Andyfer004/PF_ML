# Databricks notebook source
spark.range(1).count()

# COMMAND ----------
# MAGIC %pip install scikit-learn==1.6.1 pandas==2.3.3 scipy==1.15.3

# COMMAND ----------
# MAGIC %run ./lib_predictor

# COMMAND ----------
import json
import csv
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature

dbutils.widgets.dropdown("fuente", "mem", ["mem", "fotos"])
dbutils.widgets.text("fecha_corte", datetime.now(ZoneInfo("America/Guatemala")).date().isoformat())
source_name = dbutils.widgets.get("fuente")
base = Path("/Workspace/Users/fue22944@uvg.edu.gt/PF-ML")
filename = base / ("precios_mem.csv" if source_name == "mem" else "precios_fotos_candidatos.csv")
observations = pd.read_csv(filename).to_dict("records")
if source_name=="fotos":
    from src.price_quality import quarantine_review_flags
    with (base/"data/ocr_review_flags.csv").open(newline="") as stream:
        review_flags={(r["foto_origen"],r["combustible"]):r["motivo"] for r in csv.DictReader(stream)}
    observations=[r for r in quarantine_review_flags(observations,review_flags) if r.get("precio_q_galon") is not None]
model, report, tables = train_predictor(observations, as_of=dbutils.widgets.get("fecha_corte"))
predictions, blocked = forecast(model,tables["features_modelo"],as_of=dbutils.widgets.get("fecha_corte"))
report.update(fuente=source_name,predicciones=predictions,predicciones_bloqueadas=blocked,
              estado_calidad="fuente_oficial_retrospectiva" if source_name=="mem" else "experimental_OCR_pendiente_auditoria_humana",
              nota="MEM y fotografías son cohortes diferentes. Evaluación temporal retrospectiva; métricas corresponden al modelo evaluado antes del reajuste final.")
if source_name=="fotos":
    report["sha256_politica_revision"]=hashlib.sha256((base/"data/ocr_review_flags.csv").read_bytes()).hexdigest()

# COMMAND ----------
mlflow.set_tracking_uri("databricks")
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment("/Users/fue22944@uvg.edu.gt/PF-ML/experimento_predictor_" + source_name)
with mlflow.start_run(run_name="clasificador_semanal_" + source_name) as run:
    mlflow.log_params({"fuente":source_name,"umbral_q":report["umbral_q"],
                       "estado_calidad":report["estado_calidad"],
                       "modelo_elegido":report["modelo"],"fecha_corte":dbutils.widgets.get("fecha_corte"),
                       "features":json.dumps(FEATURES),"seed":5})
    for name, evaluation in report["validacion_modelos"].items():
        with mlflow.start_run(run_name=name,nested=True):
            mlflow.log_param("tipo",name)
            mlflow.log_metrics({"validation_accuracy":evaluation["accuracy"],"validation_macro_f1":evaluation["macro_f1"]})
    mlflow.log_metrics({"test_accuracy":report["modelo_test"]["accuracy"],
                        "test_macro_f1":report["modelo_test"]["macro_f1"],
                        "baseline_accuracy":report["baseline_test"]["accuracy"],
                        "baseline_macro_f1":report["baseline_test"]["macro_f1"]})
    example=tables["features_modelo"][FEATURES].head(3)
    signature=infer_signature(example,model.predict(example))
    evaluated=mlflow.sklearn.log_model(model.evaluation_model_,artifact_path="modelo_evaluado",
                                      signature=signature,input_example=example)
    production=mlflow.sklearn.log_model(model,artifact_path="modelo_produccion",signature=signature,input_example=example)
    report.update(mlflow_run_id=run.info.run_id,modelo_uri=production.model_uri,
                  modelo_evaluado_uri=evaluated.model_uri)
    mlflow.log_dict(report,"evaluacion/metricas.json")
    mlflow.log_dict({"predicciones":predictions,"bloqueadas":blocked},"predicciones/actual.json")
    for name, frame in tables.items():
        with __import__("tempfile").TemporaryDirectory() as directory:
            path=Path(directory)/f"{name}.csv";frame.to_csv(path,index=False)
            mlflow.log_artifact(str(path),artifact_path="oro_preview")

(base / ("resultado_predictor_"+source_name+".json")).write_text(json.dumps(report,ensure_ascii=False,indent=2))
dbutils.notebook.exit(json.dumps(report,ensure_ascii=False))

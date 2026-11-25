# Databricks notebook source
# Republica tablas Oro existentes, sin reentrenar ni modificar las tablas Delta.
import json, sys
from pathlib import Path

dbutils.widgets.text('workspace_path', '/Workspace/Users/fue22944@uvg.edu.gt/PF-ML')
base = Path(dbutils.widgets.get('workspace_path'))
sys.path.insert(0, str(base))
from src.lakehouse import config
from src.api_publication import publish_api

cfg = config(dbutils)
row = spark.sql(f"SELECT max(fecha_corte) AS fecha FROM {cfg['catalog']}.gold.metricas_modelo").first()
if row['fecha'] is None:
    raise ValueError('No existe una evaluación de Oro para publicar')
result = publish_api(spark, dbutils, cfg, str(row['fecha']))
dbutils.notebook.exit(json.dumps(result))

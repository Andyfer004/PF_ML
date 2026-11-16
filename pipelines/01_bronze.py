# Databricks notebook source
"""Fotos originales en Delta externa. Por defecto valida sin escribir."""
import json
import re

from delta.tables import DeltaTable
from pyspark.sql import functions as F

DEFAULTS = {
    "source_path": "s3://cc3105-raw-869227452861-us-east-2-an/img/",
    "catalog": "lakehouse_equipo5",
    "schema": "bronze",
    "table": "fotos_precios",
    "destination_path": "s3://cc3105-cusn-869227452861-us-east-2-an/equipo-05/fotos_precios/",
    "dry_run": "true",
}
for key, value in DEFAULTS.items():
    dbutils.widgets.text(key, value)
config = {key: dbutils.widgets.get(key).strip() for key in DEFAULTS}
for key in ("catalog", "schema", "table"):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", config[key]):
        raise ValueError(f"Identificador inválido: {key}")
if config["catalog"] != "lakehouse_equipo5":
    raise ValueError("Solo se permite el catálogo del equipo 5")
if not config["source_path"].startswith(DEFAULTS["source_path"]):
    raise ValueError("Origen fuera de la carpeta de fotos compartida")
if not config["destination_path"].startswith(
    "s3://cc3105-cusn-869227452861-us-east-2-an/equipo-05/"
):
    raise ValueError("Destino fuera del prefijo del equipo 5")
if any(part in (".", "..") for part in config["destination_path"].split("/")):
    raise ValueError("Destino con segmentos de ruta no permitidos")
if config["dry_run"].lower() not in ("true", "false"):
    raise ValueError("dry_run debe ser true o false")

table_name = ".".join(config[k] for k in ("catalog", "schema", "table"))
quoted_table = ".".join(f"`{config[k]}`" for k in ("catalog", "schema", "table"))
source = (
    spark.read.format("binaryFile").option("recursiveFileLookup", "true")
    .load(config["source_path"])
    .filter(F.lower(F.col("path")).rlike(r"\.(heic|heif|jpg|jpeg|png)$"))
    .withColumn("_source_file", F.col("path"))
    .withColumn("_content_sha256", F.sha2(F.col("content"), 256))
    .withColumn("_ingestion_timestamp", F.current_timestamp())
)
source_count = source.count()
if not source_count:
    raise ValueError("No hay imágenes: no se creará una tabla vacía")
if source.select("_source_file").distinct().count() != source_count:
    raise ValueError("La lectura contiene rutas duplicadas")

if spark.catalog.tableExists(table_name):
    detail = spark.sql(f"DESCRIBE DETAIL {quoted_table}").first()
    if detail["location"].rstrip("/") != config["destination_path"].rstrip("/"):
        raise ValueError("La tabla existente apunta a otra ruta; no se modificará")
    existing = spark.table(table_name)
    before = existing.count()
    if existing.select("_source_file").distinct().count() != before:
        raise ValueError("La tabla destino ya tiene rutas duplicadas; requiere revisión")
    new_count = source.join(existing.select("_source_file"), "_source_file", "left_anti").count()
    changed_count = (
        source.alias("s").join(existing.alias("t"), "_source_file")
        .filter(~F.col("s._content_sha256").eqNullSafe(F.col("t._content_sha256"))).count()
    )
else:
    before, new_count, changed_count = 0, source_count, 0

summary = {"table": table_name, "source_count": source_count, "rows_before": before,
           "new_files": new_count, "changed_files": changed_count,
           "destination_path": config["destination_path"], "dry_run": config["dry_run"].lower() == "true"}
if not summary["dry_run"]:
    safe_location = config["destination_path"].replace("'", "''")
    spark.sql(f"""CREATE TABLE IF NOT EXISTS {quoted_table} (
        path STRING, modificationTime TIMESTAMP, length BIGINT, content BINARY,
        _source_file STRING, _content_sha256 STRING, _ingestion_timestamp TIMESTAMP
    ) USING DELTA LOCATION '{safe_location}'
    COMMENT 'Fotos originales del profesor; ingesta incremental del equipo 5'""")
    # Una ruta modificada actualiza su contenido; un archivo sin cambios conserva auditoría.
    (DeltaTable.forName(spark, table_name).alias("t")
     .merge(source.alias("s"), "t._source_file = s._source_file")
     .whenMatchedUpdateAll(condition="NOT (t._content_sha256 <=> s._content_sha256)")
     .whenNotMatchedInsertAll().execute())
    summary["rows_after"] = spark.table(table_name).count()
    if summary["rows_after"] != before + new_count:
        raise AssertionError("El conteo posterior no coincide con las nuevas fotos")

print(json.dumps(summary))
dbutils.notebook.exit(json.dumps(summary))

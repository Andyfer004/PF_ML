# Databricks notebook source
spark.range(1).count()

# COMMAND ----------
# MAGIC %pip install pillow-heif==1.1.1 rapidocr-onnxruntime==1.4.4 opencv-python==5.0.0.93

# COMMAND ----------
import io
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from pyspark.sql import functions as F

base=Path("/Workspace/Users/fue22944@uvg.edu.gt/PF-ML")
sys.path.insert(0,str(base))
from src.lcd_ocr import LCDExtractor

dbutils.widgets.dropdown("input_mode","raw_preview",["raw_preview","bronze"])
dbutils.widgets.text("limit","5")
limit=int(dbutils.widgets.get("limit"))
if not 1<=limit<=500:
    raise ValueError("limit debe estar entre 1 y 500")
source="s3://cc3105-raw-869227452861-us-east-2-an/img/"
if dbutils.widgets.get("input_mode")=="bronze":
    files=spark.table("lakehouse_equipo5.bronze.fotos_precios")
else:
    files=spark.read.format("binaryFile").option("recursiveFileLookup","true").load(source)
files=files.filter(F.lower(F.col("path")).rlike(r"\.(heic|heif|jpg|jpeg|png)$")).orderBy("path").limit(limit)
size=files.agg(F.sum("length").alias("bytes")).first()["bytes"] or 0
if size>256*1024*1024:
    raise ValueError("Particionar el lote: supera el límite del diagnóstico en driver")
records=files.select("path","content").collect()
templates=json.loads((base/"data/ocr_layout_templates.json").read_text())
results=[];errors=[]
with tempfile.TemporaryDirectory(prefix="equipo05_ocr_") as directory:
    for template in templates:
        reference=spark.read.format("binaryFile").load(source+template["archivo"]).select("content").first()
        filename=Path(directory)/template["archivo"];filename.parent.mkdir(parents=True,exist_ok=True)
        filename.write_bytes(bytes(reference.content))
    extractor=LCDExtractor(tesseract=False,template_root=directory,template_config=base/"data/ocr_layout_templates.json")
    for index,record in enumerate(records):
        try:
            result=extractor.extract(io.BytesIO(bytes(record.content)),record.path)
            results.extend(result["resultados"])
        except Exception as exc:
            errors.append({"foto_origen":record.path,"error":f"{type(exc).__name__}: {exc}"})
        print(f"Procesadas {index+1}/{len(records)}")

cutoff=datetime.now(ZoneInfo("America/Guatemala")).date().isoformat()
for row in results:
    if row.get("fecha") is None or row["fecha"]>cutoff:
        row["precio_q_galon"]=None;row["estado"]="requiere_revision"
        row["motivos_revision"].append("FECHA_INVALIDA_O_FUTURA")
accepted=[r for r in results if r.get("precio_q_galon") and r["combustible"] in ("diesel","regular","super")]
for row in accepted:
    row["ubicacion"]="muestra_fotos_curso";row["modalidad"]="no_identificada"
if accepted:
    pd.DataFrame(accepted).to_csv(base/"precios_fotos_candidatos.csv",index=False)
report={"fotos":len(records),"candidatos_modelo":len(accepted),"resultados":results,"errores_foto":errors,
        "input_mode":dbutils.widgets.get("input_mode"),"nota":"Precios candidatos; publicación Plata pendiente de auditoría humana y permisos."}
(base/"ocr_resultado_validado.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
dbutils.notebook.exit(json.dumps({k:v for k,v in report.items() if k not in ("resultados",)},ensure_ascii=False))

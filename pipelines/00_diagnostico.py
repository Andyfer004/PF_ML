# Databricks notebook source
spark.range(1).count()

# COMMAND ----------
# MAGIC %pip install pillow-heif==1.1.1 rapidocr-onnxruntime==1.4.4

# COMMAND ----------
import io
import json
from collections import Counter
from datetime import datetime, timedelta

import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from rapidocr_onnxruntime import RapidOCR
from pyspark.sql import functions as F

register_heif_opener()
dbutils.widgets.text("source_path", "s3://cc3105-raw-869227452861-us-east-2-an/img/")
dbutils.widgets.text("ocr_sample_size", "3")
source_path = dbutils.widgets.get("source_path")
sample_size = int(dbutils.widgets.get("ocr_sample_size"))
if not 0 <= sample_size <= 5:
    raise ValueError("ocr_sample_size debe estar entre 0 y 5")
if not source_path.startswith("s3://cc3105-raw-869227452861-us-east-2-an/img/"):
    raise ValueError("El diagnóstico solo lee la carpeta de fotos del profesor")

files = (
    spark.read.format("binaryFile")
    .option("recursiveFileLookup", "true")
    .load(source_path)
    .filter(F.lower(F.col("path")).rlike(r"\.(heic|heif|jpg|jpeg|png)$"))
    .select("path", "length", "content")
    .orderBy("path")
)
size = files.agg(F.count("path").alias("n"), F.sum("length").alias("bytes")).first()
if size["n"] > 500 or (size["bytes"] or 0) > 256 * 1024 * 1024:
    raise ValueError("Muestra demasiado grande para diagnóstico en driver; particionar por lote")
rows = files.collect()
records = []
for row in rows:
    record = {"foto_origen": row.path, "bytes": row.length}
    try:
        with Image.open(io.BytesIO(bytes(row.content))) as image:
            exif = image.getexif()
            details = exif.get_ifd(34665)
            raw_date = details.get(36867) or details.get(36868) or exif.get(306)
            record.update({"fecha_exif": str(raw_date) if raw_date else None,
                           "camara": exif.get(272), "ancho": image.width, "alto": image.height})
            if raw_date:
                parsed = datetime.strptime(str(raw_date)[:19], "%Y:%m:%d %H:%M:%S")
                week = parsed.date() - timedelta(days=(parsed.weekday() - 1) % 7)
                record.update({"fecha": parsed.date().isoformat(), "semana": week.isoformat()})
    except Exception as exc:
        record["error_metadata"] = f"{type(exc).__name__}: {exc}"
    records.append(record)

dated = [r for r in records if r.get("fecha")]
report = {
    "source_path": source_path, "fotos": len(records),
    "fotos_con_fecha": len(dated), "fotos_sin_fecha": len(records) - len(dated),
    "fecha_min": min((r["fecha"] for r in dated), default=None),
    "fecha_max": max((r["fecha"] for r in dated), default=None),
    "fotos_por_semana": dict(sorted(Counter(r["semana"] for r in dated).items())),
    "metadata": records, "ocr_muestra": [],
    "nota": "Diagnóstico: textos OCR sin validar; no son precios aceptados ni métricas de exactitud.",
}

# COMMAND ----------
if sample_size and rows:
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
    indexes = sorted(set(round(i * (len(rows) - 1) / max(1, sample_size - 1))
                         for i in range(sample_size)))
    for index in indexes:
        row = rows[index]
        item = {"foto_origen": row.path, "lecturas": []}
        try:
            with Image.open(io.BytesIO(bytes(row.content))) as image:
                oriented = ImageOps.exif_transpose(image).convert("RGB")
            oriented.thumbnail((2000, 2000))
            # Imagen completa y región inferior: no se asume la marca por el nombre.
            views = {"completa": oriented,
                     "inferior": oriented.crop((0, int(oriented.height * 0.5),
                                                oriented.width, oriented.height))}
            for view_name, view in views.items():
                result, elapsed = engine(np.asarray(view)[:, :, ::-1].copy())
                item["lecturas"].append({
                    "vista": view_name,
                    "lineas": [{"texto": line[1], "confianza": float(line[2]),
                                "bbox": np.asarray(line[0]).tolist()} for line in (result or [])],
                })
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        report["ocr_muestra"].append(item)

print(json.dumps({k: v for k, v in report.items() if k not in ("metadata", "ocr_muestra")},
                 ensure_ascii=False))
dbutils.notebook.exit(json.dumps(report, ensure_ascii=False))

# Databricks notebook source
spark.range(1).count()

# COMMAND ----------
# MAGIC %pip install pillow-heif==1.1.1 rapidocr-onnxruntime==1.4.4

# COMMAND ----------
# MAGIC %run ./lib_price_quality

# COMMAND ----------
import io
import json
from datetime import datetime

import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from rapidocr_onnxruntime import RapidOCR
from pyspark.sql import functions as F

register_heif_opener()
dbutils.widgets.text("source_path", "s3://cc3105-raw-869227452861-us-east-2-an/img/")
dbutils.widgets.text("sample_files", "IMG_2976.HEIC,IMG_6732.HEIC,IMG_8271.HEIC,IMG_8286.HEIC,IMG_8810.HEIC")
source_path = dbutils.widgets.get("source_path")
if not source_path.startswith("s3://cc3105-raw-869227452861-us-east-2-an/img/"):
    raise ValueError("Origen no autorizado para la prueba")
names = [name.strip() for name in dbutils.widgets.get("sample_files").split(",") if name.strip()]
if not 1 <= len(names) <= 20:
    raise ValueError("Seleccionar de 1 a 20 archivos para esta prueba")
files = (spark.read.format("binaryFile").option("recursiveFileLookup", "true").load(source_path)
         .withColumn("filename", F.regexp_extract("path", r"([^/]+)$", 1))
         .filter(F.col("filename").isin(names)).orderBy("path").collect())
engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
report = {"extractor_version": EXTRACTOR_VERSION, "modo": "preview_sin_escritura",
          "fotos": len(files), "nombres_no_encontrados": sorted(set(names) - {r.filename for r in files}),
          "resultados": [], "ocr": [], "errores_foto": []}


def coordinate(value, reference):
    parts = [float(x) for x in value]
    result = parts[0] + parts[1] / 60 + parts[2] / 3600
    return -result if reference in ("S", "W") else result


for row in files:
    try:
        with Image.open(io.BytesIO(bytes(row.content))) as image:
            exif = image.getexif()
            details = exif.get_ifd(34665)
            raw_date = details.get(36867) or details.get(36868) or exif.get(306)
            observed_date = datetime.strptime(str(raw_date)[:19], "%Y:%m:%d %H:%M:%S").date() if raw_date else None
            gps = exif.get_ifd(34853)
            location = None
            if all(key in gps for key in (1, 2, 3, 4)):
                lat = coordinate(gps[2], gps[1])
                lon = coordinate(gps[4], gps[3])
                location = f"gps:{lat:.4f},{lon:.4f}"
            oriented = ImageOps.exif_transpose(image).convert("RGB")
        oriented.thumbnail((2000, 2000))
        views = [("completa", oriented, 0),
                 ("inferior", oriented.crop((0, oriented.height // 2, oriented.width, oriented.height)),
                  oriented.height // 2)]
        candidates_by_view = []
        for view_name, view, offset_y in views:
            # Los dígitos de LCD no deben girarse 180 grados por el clasificador de texto.
            result, _ = engine(np.asarray(view)[:, :, ::-1].copy(), use_cls=False)
            lines = [{"texto": line[1], "confianza": float(line[2]),
                      "bbox": [[float(x), float(y) + offset_y] for x, y in line[0]]}
                     for line in (result or [])]
            candidates_by_view.append(labelled_prices(lines, oriented.width, oriented.height))
            report["ocr"].append({"foto_origen": row.path, "vista": view_name, "lineas": lines})
        for fuel in FUELS:
            readings = [candidates[fuel] for candidates in candidates_by_view if fuel in candidates]
            reasons = validate_candidate(fuel, observed_date, readings)
            report["resultados"].append({
                "foto_origen": row.path, "fecha": observed_date.isoformat() if observed_date else None,
                "combustible": fuel, "ubicacion": location, "modalidad": None,
                "precio_q_galon": readings[0]["precio"] if readings and not reasons else None,
                "lecturas": readings, "motivos_revision": reasons,
                "estado": "candidato" if not reasons else "requiere_revision",
            })
    except Exception as exc:
        report["errores_foto"].append({"foto_origen": row.path, "error": f"{type(exc).__name__}: {exc}"})

report["candidatos"] = sum(r["estado"] == "candidato" for r in report["resultados"])
report["requiere_revision"] = sum(r["estado"] == "requiere_revision" for r in report["resultados"])
report["nota"] = "Concordancia de dos vistas del mismo motor no demuestra exactitud. Revisar al menos 20 fotos antes de reportar calidad OCR. No publica Plata."
dbutils.notebook.exit(json.dumps(report, ensure_ascii=False))

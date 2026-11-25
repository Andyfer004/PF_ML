# Databricks notebook source
spark.range(1).count()

# COMMAND ----------
# MAGIC %pip install pillow-heif==1.1.1

# COMMAND ----------
import base64
import csv
import html
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()
dbutils.widgets.text("workspace_path", "/Workspace/Users/fue22944@uvg.edu.gt/PF-ML")
project_path = Path(dbutils.widgets.get("workspace_path"))
template_path = project_path / "evaluacion_ocr_manual.csv"
if not template_path.exists():template_path = project_path / "data/evaluacion_ocr_manual.csv"
with template_path.open(newline="", encoding="utf-8") as stream:
    template = list(csv.DictReader(stream))
options = [row["foto_origen"] for row in template]
if not options:
    raise ValueError("La muestra de revisión está vacía")
dbutils.widgets.dropdown("foto_origen", options[0], options)
for key in ("precio_diesel_manual", "precio_regular_manual", "precio_super_manual",
            "modalidad_manual", "ubicacion_manual", "revisor", "observaciones", "confirmar_archivo"):
    dbutils.widgets.text(key, "")
dbutils.widgets.dropdown("guardar", "false", ["false", "true"])

# COMMAND ----------
selected_path = dbutils.widgets.get("foto_origen")
if selected_path not in options:
    raise ValueError("La foto no pertenece a la muestra de revisión")
rows = spark.read.format("binaryFile").load(selected_path).select("content").collect()
if len(rows) != 1:
    raise ValueError("La ruta debe identificar exactamente una foto")
with Image.open(io.BytesIO(bytes(rows[0].content))) as image:
    oriented = ImageOps.exif_transpose(image).convert("RGB")
oriented.thumbnail((1800, 2400))
preview = io.BytesIO()
oriented.save(preview, format="JPEG", quality=95)
encoded = base64.b64encode(preview.getvalue()).decode()
displayHTML(f'<p>{html.escape(selected_path)}</p><img style="max-width:100%" src="data:image/jpeg;base64,{encoded}">')
print("La imagen se muestra dentro de Databricks. Ingresar los valores visibles; no estimarlos por diferencias entre combustibles.")
print("Para guardar, completar revisor y confirmar_archivo con el nombre exacto de esta foto. Los widgets conservan valores entre ejecuciones: revisar todos los campos al cambiar de foto.")

# COMMAND ----------
labels_path = project_path / "referencias_ocr_revisadas.json"
if dbutils.widgets.get("guardar") == "true":
    filename = selected_path.rsplit("/", 1)[-1]
    if dbutils.widgets.get("confirmar_archivo").strip() != filename:
        raise ValueError("Confirmar el nombre exacto de la foto evita guardar valores de otra imagen")
    reviewer = dbutils.widgets.get("revisor").strip()
    if not reviewer:
        raise ValueError("Falta identificar al revisor")
    record = next(dict(row) for row in template if row["foto_origen"] == selected_path)
    missing=[]
    for fuel in ("diesel", "regular", "super"):
        key = f"precio_{fuel}_manual"
        raw = dbutils.widgets.get(key).strip()
        if not raw:
            if not dbutils.widgets.get("observaciones").strip():
                raise ValueError("Si un precio es ilegible, dejarlo vacío y explicar el motivo en observaciones")
            record[key]="";missing.append(fuel)
            continue
        value = Decimal(raw.replace(",", "."))
        if not value.is_finite() or value <= 0 or value.as_tuple().exponent < -2:
            raise ValueError(f"Precio inválido: {key}")
        record[key] = str(value.quantize(Decimal("0.01")))
    for key in ("modalidad_manual", "ubicacion_manual", "observaciones"):
        record[key] = dbutils.widgets.get(key).strip()
    record["revisor"] = reviewer
    record["confirmado_equipo"]="true"
    record["combustibles_ilegibles"]=missing
    record["fecha_revision_utc"] = datetime.now(timezone.utc).isoformat()
    labels = json.loads(labels_path.read_text()) if labels_path.exists() else []
    labels = [row for row in labels if row["foto_origen"] != selected_path] + [record]
    labels_path.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
    print(f"Guardada referencia de {filename}. Fotos revisadas: {len(labels)} de {len(options)}")
else:
    print("Vista previa: no se guardaron referencias. Cambiar guardar a true únicamente después de revisar los campos.")

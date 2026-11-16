#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$PROJECT_DIR/scripts/databricks.sh"
DEST="/Users/fue22944@uvg.edu.gt/PF-ML"

bash "$CLI" workspace mkdirs "$DEST"
for notebook in 00_diagnostico 01_bronze 02_extraccion_preview 03_revision_manual 04_predictor 05_ocr_validado; do
  bash "$CLI" workspace import "$DEST/$notebook" \
    --file "$PROJECT_DIR/pipelines/$notebook.py" \
    --format SOURCE --language PYTHON --overwrite
done
bash "$CLI" workspace import "$DEST/lib_price_quality" \
  --file "$PROJECT_DIR/src/price_quality.py" \
  --format SOURCE --language PYTHON --overwrite
bash "$CLI" workspace import "$DEST/evaluacion_ocr_manual.csv" \
  --file "$PROJECT_DIR/data/evaluacion_ocr_manual.csv" --format RAW --overwrite
bash "$CLI" workspace import "$DEST/lib_predictor" \
  --file "$PROJECT_DIR/src/predictor.py" --format SOURCE --language PYTHON --overwrite
bash "$CLI" workspace mkdirs "$DEST/src"
bash "$CLI" workspace mkdirs "$DEST/data"
for module in __init__ lcd_ocr price_quality generic_ocr; do
  bash "$CLI" workspace import "$DEST/src/$module.py" \
    --file "$PROJECT_DIR/src/$module.py" --format RAW --overwrite
done
bash "$CLI" workspace import "$DEST/data/ocr_layout_templates.json" \
  --file "$PROJECT_DIR/data/ocr_layout_templates.json" --format RAW --overwrite
bash "$CLI" workspace import "$DEST/data/ocr_review_flags.csv" \
  --file "$PROJECT_DIR/data/ocr_review_flags.csv" --format RAW --overwrite
bash "$CLI" workspace import "$DEST/precios_mem.csv" \
  --file "$PROJECT_DIR/data/external/mem/precios_normalizados.csv" --format RAW --overwrite
echo "Notebooks actualizados en $DEST. No se inició ninguna ejecución."

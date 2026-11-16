# PF-ML — Precios de combustibles en Guatemala

Proyecto del equipo 5 para extraer precios de fotografías de surtidores y clasificar la variación semanal de Súper, Regular y Diésel: **sube, estable o baja**. Los precios se expresan en quetzales por galón.

El OCR y el predictor son componentes separados. La serie oficial del Ministerio de Energía y Minas (MEM) permite entrenar el predictor sin depender de lecturas dudosas de fotografías. Las dos fuentes se evalúan por separado.

## Estado

- OCR con RapidOCR, rectificación de pantallas y asociación por etiquetas de combustible. Se procesaron 110 fotografías; los valores ambiguos se envían a revisión. Falta completar la validación humana independiente de al menos 20 fotos.
- Predictor MEM entrenado y ejecutado en Databricks con seguimiento de experimentos y artefactos en MLflow. En la evaluación temporal del corte 2026-11-16, el árbol obtuvo **61.4 % de exactitud** frente a **56.8 % del baseline**, sobre 414 casos de prueba. Macro F1: 0.576 y 0.556, respectivamente. Es una evaluación retrospectiva; las revisiones históricas de la fuente pueden afectar una evaluación operacional.
- Predictor de fotografías experimental: seis casos de prueba, insuficientes para una conclusión de desempeño. Bloquea pronósticos cuando la última observación es demasiado antigua.
- Ingesta Bronze preparada con modo de simulación y escritura idempotente. La escritura está pendiente del permiso `CREATE_EXTERNAL_TABLE` en la ubicación externa. La publicación en Silver/Gold y el servicio en DigitalOcean siguen pendientes.

## Instalación

Requiere Python 3.12. Desde la raíz del repositorio:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-model.txt
```

Las fotografías, credenciales, modelos entrenados, cachés y resultados de ejecución se mantienen fuera de Git. Las dependencias descargan sus propios modelos OCR al instalarse o inicializarse, según la configuración del paquete.

## Predictor local

Se incluye una copia del archivo público del MEM, los datos normalizados y un manifiesto con URL de origen y SHA-256. La población corresponde a la ciudad capital; no equivale al precio de una estación fotografiada.

```bash
python scripts/prepare_mem.py
python scripts/train_predictor.py --source mem
python scripts/predict.py --source mem --combustible super
```

Para reproducir el corte de la evaluación reportada:

```bash
python scripts/train_predictor.py --source mem --as-of 2026-11-16
```

El entrenamiento agrupa observaciones por semana de martes a lunes y construye objetivos a exactamente siete días. Divide cronológicamente entrenamiento, validación y prueba; ajusta transformaciones solo con entrenamiento y selecciona entre regresión logística y árbol usando validación. Evalúa frente a un baseline que conserva la última dirección conocida. Después de evaluar, reajusta el modelo elegido con los datos disponibles para producción.

Una variación mayor de Q0.10 se clasifica como subida, menor de −Q0.10 como bajada, y el resto como estable. Las etiquetas requieren semanas objetivo cerradas. Los artefactos se guardan en `output/modelos/<fuente>/<ejecución>/`, con métricas, tablas de evaluación y `modelo.joblib`. El archivo `latest.json` identifica la ejecución vigente. El comando de predicción evita pronósticos vencidos.

## Databricks

Instalar Databricks CLI y autenticar el perfil del proyecto mediante OAuth:

```bash
databricks auth login --host https://dbc-5490c6a5-5215.cloud.databricks.com --profile PF-ML
bash scripts/deploy_notebooks.sh
```

El despliegue importa archivos a `/Users/fue22944@uvg.edu.gt/PF-ML` y actualiza únicamente los archivos del proyecto. No inicia ejecuciones. Las rutas de los notebooks corresponden al workspace del equipo y deben ajustarse si se usa otro destino.

| Notebook | Función |
| --- | --- |
| `00_diagnostico` | Inventario, metadata y muestra de OCR del origen autorizado |
| `01_bronze` | Simulación e ingesta de binarios con trazabilidad; `dry_run=true` por defecto |
| `02_extraccion_preview` | Primera exploración de extracción de precios |
| `03_revision_manual` | Revisión visual con campos vacíos y confirmación explícita por foto |
| `04_predictor` | Entrenamiento por fuente, evaluación temporal y registro en MLflow |
| `05_ocr_validado` | Extracción con controles de calidad y exportación de candidatos |

El origen de fotografías es `s3://cc3105-raw-869227452861-us-east-2-an/img/`, accesible mediante la external location del curso. No se requieren credenciales AWS del profesor en este repositorio. `pipelines/validacion_bronze_job.json` define la comprobación de simulación, ingesta y repetición; requiere resolver los permisos antes de ejecutar la escritura.

En `04_predictor`, seleccionar `fuente=mem` para la serie oficial. Para `fuente=fotos`, ejecutar primero `05_ocr_validado` y revisar sus candidatos. Esta última opción conserva el estado experimental y las exclusiones por lecturas ambiguas.

## OCR y validación

Para ejecutar localmente, guardar el JSON devuelto por `00_diagnostico` como `output/diagnostico_databricks.json` y usar la conexión autenticada para descargar las imágenes autorizadas:

```bash
python scripts/download_photos.py --all
python scripts/run_ocr.py --workers 2
```

Las fotografías se guardan en `data/images/`, respetando subcarpetas. El reporte queda en `output/ocr_completo.json`. Las plantillas geométricas están en `data/ocr_layout_templates.json`; las exclusiones pendientes de confirmación están en `data/ocr_review_flags.csv`. Los precios de combustibles se leen individualmente y no se completan suponiendo diferencias fijas.

Revisar las fotos con `03_revision_manual`, identificar al revisor y confirmar cada archivo. Exportar su `referencias_ocr_revisadas.json` al directorio local `output/` y evaluar:

```bash
python scripts/evaluate_ocr.py --references output/referencias_ocr_revisadas.json
python scripts/train_predictor.py --source fotos
```

La evaluación informa cobertura, precisión entre precios extraídos y exactitud contando omisiones. Las referencias sin confirmación explícita del equipo no cierran la validación humana. El entrenamiento de fotografías sigue usando candidatos OCR y sus exclusiones; guardar referencias de evaluación no reemplaza automáticamente esos candidatos ni los convierte en datos certificados.

## Verificación

```bash
python -m unittest discover -s tests -v
```

Las pruebas cubren precios y etiquetas, cuarentena de lecturas ambiguas, evaluación con omisiones, separación temporal, semanas faltantes, semanas abiertas y bloqueo de pronósticos vencidos.

## Piloto inicial

`src/gas_pipeline.py`, `requirements.txt`, `data/lecturas_manuales.csv`, `output/gas_prices.csv` y `notebooks/01_eda_gas_prices.ipynb` conservan el piloto inicial y su EDA. Ese piloto utiliza lecturas manuales y diferencias fijas entre algunos combustibles; sus estimaciones no alimentan el predictor actual. `reportes/PF1_MLOPS.pdf` contiene la entrega anterior.

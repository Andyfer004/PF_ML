# Predicción del precio de la gasolina en Guatemala

Proyecto final de CC3105, Universidad del Valle de Guatemala. **Equipo 5.**

[![Pruebas del proyecto](https://github.com/Andyfer004/PF_ML/actions/workflows/pruebas.yml/badge.svg)](https://github.com/Andyfer004/PF_ML/actions/workflows/pruebas.yml)

El proyecto convierte fotografías de precios en tablas Delta y clasifica si súper, regular y diésel suben, bajan o se mantienen la semana siguiente. Usa semanas de martes a lunes y precios en quetzales por galón. Las fotografías y el histórico oficial del MEM se conservan como fuentes separadas.

- **Demo pública:** [interfaz web](http://165.22.137.8:8000/).
- **API:** [Swagger y consultas interactivas](http://165.22.137.8:8000/docs).
- **Repositorio público:** [Andyfer004/PF_ML](https://github.com/Andyfer004/PF_ML).
- **Databricks:** [Job del proyecto](https://dbc-5490c6a5-5215.cloud.databricks.com/jobs/164482682079093?o=7474655525361249).

La cuenta SSH asignada es `cc3105-03@165.22.137.8`. El Job existente conserva el nombre técnico `equipo-03-pipeline` y el parámetro heredado `equipo=03`. Estos identificadores no cambian el número del equipo: el catálogo es `lakehouse_equipo5` y los datos pertenecen a los prefijos del equipo 5. Se mantienen esos nombres para conservar la configuración desplegada y su historial.

## Resultados verificados

| Componente | Resultado |
| --- | --- |
| Bronce | 110 fotografías originales. Repetir la carga no duplica registros. |
| Plata | 126 registros aceptados y 278 rechazados con motivo. Una fotografía puede aportar ambos. |
| Revisión humana | 20 fotografías revisadas, 33 precios legibles, 18 extraídos y 17 correctos. |
| Calidad OCR | Precisión 94.4 %, cobertura 54.5 % y exactitud incluyendo omisiones 51.5 %. Tolerancia Q0.02. |
| Histórico MEM | 11,427 observaciones únicas, desde 2013-02-08 hasta 2026-11-10. |
| Modelo MEM | 417 casos de prueba temporal. Exactitud 58.75 % frente a 57.07 % de la línea base. |
| Macro F1 | Modelo 0.542 frente a 0.558 de la línea base: no la supera en esta métrica. |
| Orquestación | Tres tareas encadenadas, programación semanal y correo de fallo probado. |
| Pruebas | 70 pruebas Python y 12 pruebas de interfaz. GitHub Actions ejecuta ambas suites. |

La línea base repite la última dirección conocida. El modelo usa separación temporal con purga de etiquetas entre bloques; no reparte aleatoriamente las semanas. Los experimentos de MLflow conservan el modelo evaluado separado del reajustado para producción.

**La demostración es histórica.** `/prediccion?combustible=super` devuelve la evaluación de la semana siguiente al corte simulado, con fechas, probabilidad y resultado real. La semana demostrada es 2026-11-10, con corte simulado 2026-11-09. No se presenta como pronóstico vigente al día de la consulta. `modo=vigente` responde 503 cuando faltan precios recientes.

## Entregables

- [Diagrama de arquitectura elegido por el equipo](docs/arquitectura_usuario.png).
- [Informe técnico](docs/informe.pdf): cinco páginas, incluyendo el diagrama.
- [Presentación del equipo](presentacion/presentacion_jurado.pdf).
- [Resumen para el jurado](presentacion/resumen_jurado.pdf): una página con la URL pública.
- [Capturas de Databricks](docs/evidencias/fase4/README.md): historial y duración de dos ejecuciones exitosas.
- [Configuración real del cómputo](pipelines/computo_documentado.json), [Job exportado](pipelines/job_exportado.json) y [evidencia operativa](docs/evidencia_operativa.json).

El informe y la presentación se conservan como PDF finales. `python scripts/build_jury_summary.py` regenera únicamente el resumen académico. El diagrama PNG es el archivo proporcionado por el equipo; las fuentes Graphviz en `docs/antecedentes/` corresponden a versiones anteriores.

## Organización

```text
PF_ML/
├── README.md
├── docs/                         # Informe, diagrama definitivo y evidencias
│   ├── evidencias/fase4/          # Tres capturas y su manifiesto
│   └── antecedentes/             # Diagramas anteriores
├── pipelines/
│   ├── 01_bronze.py
│   ├── 02_silver.py
│   ├── 03_gold.py
│   ├── job.json                  # Plantilla reproducible
│   ├── job_exportado.json        # Configuración del Job operativo
│   ├── auxiliares/               # Revisión manual y publicación auxiliar
│   └── antecedentes/             # Prototipos y configuración clásica no ejecutada
├── src/                          # OCR, calidad, modelo y operaciones Delta
├── api/                          # FastAPI, interfaz web y Docker
├── data/                         # MEM original, referencias humanas y configuración OCR
├── scripts/                      # Despliegue, ejecución y verificación
├── tests/                        # Pruebas Python, interfaz y colección curl
└── presentacion/                 # Presentación y resumen para el jurado
```

Las fotografías originales, cachés, modelos entrenados, salidas locales, `.env`, llaves SSH y credenciales no se publican. `src/gas_pipeline.py`, la EDA y los notebooks en `pipelines/antecedentes/` son el piloto inicial, no el pipeline definitivo.

## Preparación local y pruebas

Requiere Python 3.12. Para ejecutar las pruebas sin AWS ni fotografías privadas:

```bash
git clone https://github.com/Andyfer004/PF_ML.git
cd PF_ML
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
npm --prefix tests/ui ci --no-audit --no-fund
npm --prefix tests/ui test
```

Para desarrollar OCR y entrenar localmente, instalar además `requirements-model.txt`. Los originales del MEM y su manifiesto están en `data/external/mem/`. Las referencias humanas confirmadas están en `data/evaluacion_ocr_confirmada.csv`. Las fotos requieren acceso al origen compartido y permanecen en `data/images/`, fuera de Git.

## Pipeline en Databricks

1. Autenticar Databricks CLI con el perfil del proyecto:

   ```bash
   databricks auth login --host https://dbc-5490c6a5-5215.cloud.databricks.com --profile PF-ML
   ```

2. El Git folder está creado en `/Users/fue22944@uvg.edu.gt/PF_ML`, conectado a `main` del repositorio público. Las tareas del Job apuntan a `pipelines/01_bronze`, `pipelines/02_silver` y `pipelines/03_gold` dentro de ese clon. `workspace_path` es `/Workspace/Users/fue22944@uvg.edu.gt/PF_ML`. Los widgets reciben rutas, catálogo, fecha de corte, fuente y umbral. Para sincronizar cambios y comprobar esa conexión, ejecutar `python scripts/sync_git_folder.py --update-job`.
3. Usar **Run now** en el Job compartido. Bronce carga binarios con `binaryFile` y `MERGE`; Plata reutiliza la caché o ejecuta OCR y guarda rechazos; Oro recalcula indicadores, registra MLflow y publica Parquet.
4. Para importar una copia independiente al directorio histórico del workspace, usar `python scripts/workspace_deploy.py`. Esta alternativa no reemplaza el Git folder.
5. `scripts/run_pipeline.py` permite ejecutar y conservar evidencia por API. Mantiene el cómputo del Job existente; no seleccionar `--compute classic` en este workspace.

El Job operativo está programado los martes a las 10:00, `America/Guatemala`, y avisa por correo si falla. La prueba controlada y recepción están documentadas en [evidencia de alerta](docs/evidencia_alerta.json). El profesor tiene acceso heredado al Job y los experimentos MLflow.

La [ejecución 267528779754207](https://dbc-5490c6a5-5215.cloud.databricks.com/jobs/164482682079093/runs/267528779754207?o=7474655525361249) terminó con las tres tareas en `SUCCESS` desde el Git folder. Releyó una fotografía existente, conservó las 110 filas de Bronce y reutilizó las 110 extracciones OCR. La evidencia registra las rutas de los notebooks y el commit probado.

**Cómputo real:** serverless, con Python 3.12.3 y Spark 4.2.0 registrados. El workspace rechazó crear un Job Cluster clásico porque solo admite serverless. `pipelines/computo_documentado.json` detalla las librerías reales por tarea; la conformidad docente frente al requisito de cómputo clásico sigue siendo una salvedad.

### Almacenamiento

| Uso | Ruta |
| --- | --- |
| Fotografías del profesor, lectura | `s3://cc3105-raw-869227452861-us-east-2-an/img/` |
| Bronce Delta | `s3://cc3105-cusn-869227452861-us-east-2-an/equipo-05/` |
| Plata Delta | `s3://cc3105-ag-869227452861-us-east-2-an/equipo-05/` |
| Oro Delta | `s3://cc3105-au-869227452861-us-east-2-an/equipo-05/` |
| Publicación Parquet de Oro para la API | `s3://cc3105-au-869227452861-us-east-2-an/cc3105-equipo5/api/` |

La última ruta corresponde al prefijo autorizado de la identidad AWS y contiene `current.json` y publicaciones versionadas. No es intercambiable con `equipo-05/`. Unity Catalog gobierna el acceso de Databricks; el Droplet usa sus propias credenciales AWS.

## API y despliegue

Docker aísla las dependencias fijadas en `requirements-api.lock`. El servicio usa `restart: unless-stopped` y publica el puerto 8000. Los documentos y el frontend comparten origen con la API.

| Endpoint | Uso |
| --- | --- |
| `GET /health` | Estado y publicación Oro cargada. |
| `GET /precios/actual` | Último precio por combustible. |
| `GET /precios` | Histórico con combustible, fechas, fuente y límite. |
| `GET /prediccion?combustible=super` | Evaluación histórica identificada como tal. |
| `GET /prediccion?combustible=super&modo=vigente` | Próxima semana de calendario; 503 si faltan datos recientes. |
| `GET /modelo/metricas` | Modelo y línea base. |
| `GET /docs` | Swagger. |

La API únicamente realiza operaciones de lectura. Las credenciales son administradas por el catedrático y se cargan desde `api/.env` en el servidor, con permisos `600`. No se montan perfiles AWS en el contenedor ni se incluyen claves en la imagen. La prueba de permisos confirmó que la identidad proporcionada también puede escribir; esto no se describe como una restricción IAM de solo lectura. [Política mínima de lectura propuesta](docs/iam_oro_lectura.json).

El despliegue asignado vive en `/home/cc3105-03/gasolina-equipo-05/`:

```bash
# Desde el proyecto, con la llave local asignada y Oro ya publicado:
python scripts/deploy_droplet.py
python scripts/verify_droplet.py

# Prueba pública de precios y predicción de los tres combustibles:
bash tests/consultas_api.sh http://165.22.137.8:8000
```

La primera instalación requiere configurar las variables de `api/.env.example` únicamente en el `.env` real del servidor. `--import-server-credentials` permite importar allí el perfil AWS ya existente sin sacar las claves del Droplet. Los siguientes despliegues conservan el `.env` y la interfaz de publicación. No se modifica el firewall ni otro servicio del servidor.

## Evidencias y alcance

Las [tres capturas](docs/evidencias/fase4/README.md) documentan el historial y dos ejecuciones sin reparación, con fotografías de las semanas 2026-01-27 y 2026-07-07. Ambas releyeron una foto existente y conservaron las 110 filas en Bronce. Las duraciones de la UI y `execution_duration` de la API se identifican por separado en el manifiesto.

El pipeline tiene pruebas de carga incremental, rechazo conservador, idempotencia, validación temporal y filtros de API. GitHub Actions instala dependencias y ejecuta las suites Python y Node sin credenciales. Las capturas complementan la evidencia obtenida por API.

Los aportes de los demás integrantes y la entrega del resumen al jurado 48 horas antes se gestionan por el equipo. Las predicciones históricas demuestran el modelo evaluado; actualizar las fuentes es necesario para producir un pronóstico vigente.

[Verificación de Git folders](docs/evidencias/gitfolders.json) y [ejecución validada de GitHub Actions](docs/evidencias/github_actions.json) conservan los identificadores y commits comprobados, sin credenciales.

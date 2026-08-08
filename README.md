# PF-ML

Pipeline determinista, sin LLM ni servicios de IA, para fotografias HEIC de
surtidores Shell. Usa ExifTool para metadata y OpenCV para localizar y rectificar
las cuatro pantallas inferiores.

## Entorno

```bash
bash scripts/setup_env.sh
source .venv/bin/activate
```

Si `python` esta reemplazado por un alias del shell:

```bash
./.venv/bin/python src/gas_pipeline.py
```

ExifTool permite exportar toda la metadata disponible:

```bash
# macOS
brew install exiftool

# Ubuntu/Debian
sudo apt install libimage-exiftool-perl
```

## Entrada

- Imagenes HEIC: `data/images/`.
- Lectura humana del display superior e inferior: `data/lecturas_manuales.csv`.
- Eventos mundiales fechados y con fuente: `data/eventos_globales.csv`.

Diesel se almacena, pero no se estima porque su precio no sigue una diferencia
fija. A partir de la venta y los galones se calcula Super; Regular se estima un
quetzal abajo y V-Power cincuenta centavos arriba.

## Salida

```bash
python src/gas_pipeline.py
```

En la primera ejecucion, el pipeline descarga y guarda en
`data/external/series_mercado.csv` los precios diarios Brent y WTI publicados por
FRED/EIA. Para renovar la cache:

```bash
python src/gas_pipeline.py --actualizar-externos
```

Cada foto se cruza con la ultima observacion de mercado disponible y con los
eventos de los 21 dias anteriores. Nunca se usan eventos o precios posteriores a
la fecha de la imagen. Si no hay red, se reutiliza la cache y
`datos_externos_estado` informa cualquier dato faltante.

- `output/gas_prices.csv`: resumen ordenado por fecha, valores manuales,
  estimados, diferencias, mercado internacional, eventos y flags `1/0`.
- `output/metadata/`: JSON completo de ExifTool por imagen.
- `output/crops/`: los cuatro LCD inferiores rectificados por OpenCV.
- `output/records/`: registro auditable que relaciona imagen, metadata y recortes.
- `notebooks/01_eda_gas_prices.ipynb`: EDA de la fase de entendimiento de datos.

Cada precio comparable tiene su propio flag. `todos_match_flag=1` y
`estado_flag=ENCENDIDO` significan que Regular, Super y V-Power coinciden con la
lectura manual dentro de una tolerancia de dos centavos. Cualquier dato faltante,
pantalla no detectada o diferencia mayor enciende `requiere_revision_flag=1`.

Para ejecutar el EDA, abre el notebook y selecciona el kernel de `.venv`.

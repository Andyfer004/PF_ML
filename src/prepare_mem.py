"""Normaliza el histórico diario oficial del MEM sin mezclarlo con fotos de estaciones."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
URL = "https://mem.gob.gt/wp-content/uploads/2026/11/Precios-Promedio-Nacionales-Diarios-2026.xlsx"


def normalize(filename, as_of=None):
    raw = pd.read_excel(filename, header=None)
    rows = []
    cutoff = pd.Timestamp(as_of or datetime.now(ZoneInfo("America/Guatemala")).date())
    for row in raw.itertuples(index=False, name=None):
        if not isinstance(row[0], (pd.Timestamp, datetime)):
            continue
        observed = pd.Timestamp(row[0]).normalize()
        if observed > cutoff:
            continue
        for column, fuel in ((2,"super"),(3,"regular"),(4,"diesel")):
            price = pd.to_numeric(row[column],errors="coerce")
            if pd.notna(price) and 0 < price < 100:
                rows.append({"fecha":observed.date().isoformat(),"combustible":fuel,
                             "precio_q_galon":float(price),"ubicacion":"ciudad_capital_MEM",
                             "modalidad":"no_especificada_en_archivo","fuente":"MEM_diario",
                             "fuente_url":URL})
    return rows


if __name__ == "__main__":
    filename = ROOT / "data/external/mem/precios_diarios_2026.xlsx"
    rows = normalize(filename)
    output = ROOT / "data/external/mem/precios_normalizados.csv"
    pd.DataFrame(rows).to_csv(output,index=False)
    manifest = {"fuente_url":URL,"sha256":hashlib.sha256(filename.read_bytes()).hexdigest(),
                "filas":len(rows),"fecha_min":min(r["fecha"] for r in rows),
                "fecha_max":max(r["fecha"] for r in rows),
                "nota":"Serie MEM ciudad capital. No equivale al precio de la estación fotografiada. Archivo retrospectivo: validar revisiones y fechas de publicación para backtest operacional."}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps(manifest,ensure_ascii=False))

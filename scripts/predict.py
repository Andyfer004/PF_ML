"""Consulta el predictor guardado y conserva la identidad de la fuente."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.predictor import forecast


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",choices=["mem","fotos"],default="mem")
    parser.add_argument("--combustible",choices=["super","regular","diesel"],required=True)
    args=parser.parse_args()
    pointer=json.loads((ROOT/"output/modelos"/args.source/"latest.json").read_text())
    directory=ROOT/pointer["directorio"]
    report=json.loads((directory/"metricas.json").read_text())
    today=datetime.now(ZoneInfo("America/Guatemala")).date().isoformat()
    if today < report["fecha_corte"]:
        raise ValueError("No se puede usar un modelo entrenado después de la fecha de consulta")
    model=joblib.load(directory/"modelo.joblib")
    features=pd.read_csv(directory/"features_modelo.csv",parse_dates=["semana","semana_objetivo"])
    predictions,blocked=forecast(model,features,as_of=today)
    rows=[r for r in predictions if r["combustible"]==args.combustible]
    output={"fuente":args.source,"estado_calidad":report["estado_calidad"],"fecha_corte":report["fecha_corte"],
            "prediccion":rows[0] if rows else None,
            "pendientes":[r for r in blocked if r["combustible"]==args.combustible]}
    print(json.dumps(output,ensure_ascii=False,indent=2))

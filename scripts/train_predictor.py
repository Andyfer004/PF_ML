"""Entrena, evalúa y guarda el clasificador semanal de una sola fuente identificada."""
import argparse
import csv
import hashlib
import json
import sys
from datetime import date,datetime,timezone
from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.predictor import forecast,train_predictor,today_gt,horizon_for_next_week
from src.price_quality import quarantine_review_flags


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",choices=["fotos","mem"],required=True)
    parser.add_argument("--as-of",default=today_gt().isoformat())
    parser.add_argument('--horizon-weeks',choices=['auto','1','2'],default='auto')
    args = parser.parse_args()
    if args.source == "mem":
        source = ROOT / "data/external/mem/precios_normalizados.csv"
        rows = pd.read_csv(source).to_dict("records")
        quality = "fuente_oficial_retrospectiva"
    else:
        source = ROOT / "output/ocr_completo.json"
        with (ROOT/"data/ocr_review_flags.csv").open(newline="") as stream:
            flags={(r["foto_origen"],r["combustible"]):r["motivo"] for r in csv.DictReader(stream)}
        reviewed=quarantine_review_flags(json.loads(source.read_text())["resultados"],flags)
        rows = [r for r in reviewed
                if r.get("precio_q_galon") is not None and r["combustible"] in ("super","regular","diesel")]
        # Se conserva la población de fotos como cohorte separada del MEM.
        for row in rows:
            row["ubicacion"] = "muestra_fotos_curso"
            row["modalidad"] = "no_identificada"
        frame = pd.DataFrame(rows)
        key = ["fecha","combustible","ubicacion","modalidad"]
        conflicts = frame.groupby(key)["precio_q_galon"].transform("nunique") > 1
        rows = frame[~conflicts].to_dict("records")
        columns=["fecha","combustible","precio_q_galon","ubicacion","modalidad","foto_origen"]
        pd.DataFrame(rows)[columns].to_csv(ROOT/"output/precios_fotos_candidatos.csv",index=False)
        quality = "OCR_candidatos_pendiente_auditoria_humana"
    horizon=horizon_for_next_week(rows,args.as_of) if args.horizon_weeks=='auto' and args.source=='mem' else (1 if args.horizon_weeks=='auto' else int(args.horizon_weeks))
    model,report,tables = train_predictor(rows,as_of=args.as_of,horizon_weeks=horizon)
    predictions,blocked = forecast(model,tables["features_modelo"],as_of=args.as_of)
    report.update(fuente=args.source,estado_calidad=quality,
                  sha256_entrada=hashlib.sha256(source.read_bytes()).hexdigest(),
                  fecha_corte=args.as_of,predicciones=predictions,predicciones_bloqueadas=blocked)
    if args.source=="fotos":
        report["sha256_politica_revision"]=hashlib.sha256((ROOT/"data/ocr_review_flags.csv").read_bytes()).hexdigest()
    directory = ROOT / "output/modelos" / args.source / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    joblib.dump(model,directory / "modelo.joblib")
    (directory / "metricas.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    for name,frame in tables.items():frame.to_csv(directory / f"{name}.csv",index=False)
    (directory.parent / "latest.json").write_text(json.dumps({"directorio":str(directory.relative_to(ROOT))}))
    print(json.dumps({"directorio":str(directory),"fuente":args.source,"modelo":report["modelo"],
                      "modelo_test":report["modelo_test"],"baseline_test":report["baseline_test"],
                      "n_supervisados":report["ejemplos_supervisados"],"bloqueadas":blocked},ensure_ascii=False,indent=2))

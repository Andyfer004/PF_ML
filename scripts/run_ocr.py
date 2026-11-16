"""Ejecuta OCR sobre el manifiesto autorizado, con caché por imagen/código/plantilla."""
import argparse
import concurrent.futures
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = "s3://cc3105-raw-869227452861-us-east-2-an/img/"
ENGINE = None
CODE_SIGNATURE = None


def init_worker():
    global ENGINE, CODE_SIGNATURE
    import cv2
    from src.lcd_ocr import LCDExtractor
    cv2.setNumThreads(2)
    ENGINE = LCDExtractor()
    CODE_SIGNATURE = b"".join((ROOT / filename).read_bytes() for filename in
                               ("src/lcd_ocr.py","src/price_quality.py","src/generic_ocr.py",
                                "data/ocr_layout_templates.json","data/ocr_review_flags.csv"))


def process(record):
    source = record["foto_origen"]
    if not source.startswith(SOURCE):
        raise ValueError("Origen no autorizado")
    filename = ROOT / "data/images" / source[len(SOURCE):]
    digest = hashlib.sha256(filename.read_bytes() + CODE_SIGNATURE).hexdigest()
    cache = ROOT / ".cache/ocr_v2" / (digest + ".json")
    if cache.exists():
        result = json.loads(cache.read_text())
        # Dos formatos pueden representar la misma foto; conservar su ruta de origen.
        result["foto_origen"] = source
        for row in result["resultados"]:
            row["foto_origen"] = source
        return result
    try:
        result = ENGINE.extract(filename, source)
    except Exception as exc:
        result = {"foto_origen": source, "resultados": [], "error": f"{type(exc).__name__}: {exc}"}
    result["sha256_imagen"] = hashlib.sha256(filename.read_bytes()).hexdigest()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    records = json.loads((ROOT / "output/diagnostico_databricks.json").read_text())["metadata"]
    if args.limit:
        records = records[:args.limit]
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers, initializer=init_worker) as executor:
        for result in executor.map(process, records):
            results.append(result)
            if len(results) % 5 == 0:
                print(f"Procesadas {len(results)}/{len(records)}", flush=True)
    report = {"version": "lcd-consensus-labels-v3", "fotos": len(results), "fotos_detalle": results,
              "resultados": [row for item in results for row in item["resultados"]],
              "errores_foto": [item for item in results if item.get("error")]}
    report["candidatos"] = sum(row["precio_q_galon"] is not None for row in report["resultados"])
    report["requiere_revision"] = sum(row["precio_q_galon"] is None for row in report["resultados"])
    (ROOT / "output/ocr_completo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ("fotos_detalle","resultados","errores_foto")}), flush=True)

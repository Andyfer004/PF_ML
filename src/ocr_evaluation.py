"""Compara candidatos con referencias humanas; las omisiones cuentan como errores."""
import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path


def evaluate(report, references, tolerance=Decimal("0.02")):
    by_filename = {}
    for row in report["resultados"]:
        name = Path(row["foto_origen"]).name
        key = (name, row["combustible"])
        if key in by_filename:
            raise ValueError(f"Nombre ambiguo en el lote: {name}; evaluar por ruta completa")
        by_filename[key] = row
    sampled_names = {name for name, fuel in by_filename}
    expected = extracted = correct = 0
    reviewed_photos = set()
    human_photos = set()
    legible_photos = set()
    detail = []
    for reference in references:
        name = reference.get("archivo") or Path(reference.get("foto_origen", "")).name
        if name not in sampled_names:
            continue
        # La plantilla nueva solo es referencia cuando tiene revisor identificado.
        if "revisor" in reference and not reference["revisor"].strip():
            continue
        has_reference = False
        for fuel in ("diesel", "regular", "super"):
            raw = reference.get(f"precio_{fuel}_manual") or reference.get(f"precio_{fuel}")
            if not raw:
                continue
            has_reference = True
            expected += 1
            candidate = by_filename.get((name, fuel), {}).get("precio_q_galon")
            if candidate is not None:
                extracted += 1
            is_correct = candidate is not None and abs(Decimal(candidate) - Decimal(raw)) <= tolerance
            correct += int(is_correct)
            detail.append({"archivo": name, "combustible": fuel, "manual": raw,
                           "extraido": candidate, "correcto": is_correct})
        explicitly_reviewed=(reference.get('revisor','').strip() and reference.get('confirmado_equipo','').lower()=='true' and reference.get('observaciones','').strip())
        if has_reference:legible_photos.add(name)
        if has_reference or explicitly_reviewed:
            reviewed_photos.add(name)
            # Referencias nuevas requieren confirmación explícita además de revisor.
            confirmed = reference.get("confirmado_equipo", "").lower() == "true"
            legacy = "revisor" not in reference and "confirmado_equipo" not in reference
            if legacy or (reference.get("revisor", "").strip() and confirmed):
                human_photos.add(name)
    return {
        "fotos_con_referencia": len(reviewed_photos), "fotos_revisadas":len(reviewed_photos),
        "fotos_con_referencia_legible":len(legible_photos), "precios_esperados": expected,
        "precios_extraidos": extracted, "precios_correctos": correct,
        "exactitud_incluyendo_omisiones": correct / expected if expected else None,
        "cobertura": extracted / expected if expected else None,
        "precision_sobre_extraidos": correct / extracted if extracted else None,
        "fotos_con_referencia_humana":len(human_photos),
        "estado_validacion":"REFERENCIAS_HUMANAS_CONFIRMADAS" if reviewed_photos and len(human_photos)==len(reviewed_photos) else "EXPLORATORIA_REFERENCIAS_NO_CONFIRMADAS",
        "precios_sin_referencia_legible":max(0,len(reviewed_photos)*3-expected),
        "cumple_minimo_20_fotos": len(human_photos) >= 20,
        "tolerancia_q": str(tolerance), "detalle": detail,
    }

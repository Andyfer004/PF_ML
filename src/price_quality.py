"""Validación conservadora de candidatos OCR; no infiere precios entre combustibles."""
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

FUELS = ("diesel", "regular", "super")
EXTRACTOR_VERSION = "rapidocr-1.4.4-no-cls-labels-v1"


def quarantine_review_flags(rows, flags):
    """Un aviso de revisión rechaza el candidato; nunca lo sustituye por una conjetura."""
    result=[]
    for original in rows:
        row=dict(original)
        reason=flags.get((row["foto_origen"],row["combustible"]))
        if reason:
            if row.get("precio_q_galon") is not None:
                row["precio_sin_validar"]=row["precio_q_galon"]
            row["precio_q_galon"]=None;row["estado"]="requiere_revision"
            row["motivos_revision"]=list(dict.fromkeys([*row.get("motivos_revision",[]),reason]))
        result.append(row)
    return result


def parse_price(text):
    """Exige dos decimales explícitos. No inventa puntos ni reemplaza letras."""
    match = re.fullmatch(r"\s*(?:Q\.?\s*)?(\d{1,3})[.,](\d{2})\s*", text, re.IGNORECASE)
    return Decimal(f"{match[1]}.{match[2]}") if match else None


def normalize_fuel(text):
    normalized = "".join(c for c in unicodedata.normalize("NFD", text.lower())
                         if unicodedata.category(c) != "Mn")
    found = [fuel for fuel in FUELS if re.search(rf"\b{fuel}\b", normalized)]
    return found[0] if len(found) == 1 else None


def identify_panel_fuels(regions, lines, height):
    """Asigna etiquetas visibles a paneles; soporta el orden inverso del surtidor."""
    options = []
    shell = False
    for line in lines:
        points=line["bbox"]
        lx=sum(p[0] for p in points)/len(points);ly=sum(p[1] for p in points)/len(points)
        if ly < height*.5 or line["confianza"] < .85:
            continue
        text=line["texto"].lower()
        shell=shell or "shell" in text
        fuel="vpower" if re.search(r"v[\s-]*power",text) else normalize_fuel(text)
        if fuel is None:
            continue
        for index,region in enumerate(regions):
            box=region["bbox"];x=sum(p[0] for p in box)/4;y=sum(p[1] for p in box)/4
            width=max(p[0] for p in box)-min(p[0] for p in box)
            if -.02*height < ly-y < .32*height and abs(lx-x) < width:
                options.append((abs(lx-x)/width+.1*abs(ly-y)/height,index,fuel))
    mapping={};used=set()
    for distance,index,fuel in sorted(options):
        if index not in mapping and fuel not in used:
            mapping[index]=fuel;used.add(fuel)
    # Una etiqueta oculta puede resolverse solo con cuatro paneles Shell y otras
    # tres etiquetas distintas visibles; nunca con el orden izquierda-derecha.
    if shell and len(regions)==4 and len(mapping)==3:
        remaining={"diesel","regular","super","vpower"}-used
        missing=set(range(4))-set(mapping)
        mapping[missing.pop()]=remaining.pop()
    return mapping


def week_start(value):
    return value - timedelta(days=(value.weekday() - 1) % 7)


def transaction_unit_price(lines, height):
    """Solo verifica una transacción claramente leída; no asigna su combustible."""
    totals=[];volumes=[]
    for line in lines:
        y=sum(point[1] for point in line["bbox"])/len(line["bbox"])
        if y > height*.35 or line["confianza"] < .95:
            continue
        text=re.sub(r"\s+","",line["texto"])
        total=parse_price(text)
        if total is not None and 80 <= total <= 1000:
            totals.append(total)
        if re.fullmatch(r"\d{1,2}\.\d{3}",text):
            volume=Decimal(text)
            if 0 < volume <= 50:volumes.append(volume)
    if len(set(totals))==len(set(volumes))==1:
        unit=(totals[0]/volumes[0]).quantize(Decimal(".01"))
        return unit if 10<=unit<=80 else None
    return None


def labelled_prices(lines, width, height, min_confidence=0.90):
    """Relaciona números inferiores con su etiqueta debajo en el mismo panel.

    Las coordenadas deben usar la imagen orientada completa. Ante ambigüedad no
    produce un candidato. No asume un orden Shell ni identifica diésel por descarte.
    """
    labels, prices = [], []
    for line in lines:
        points = line["bbox"]
        x = sum(p[0] for p in points) / len(points)
        y = sum(p[1] for p in points) / len(points)
        if y < height * 0.5 or line["confianza"] < min_confidence:
            continue
        fuel = normalize_fuel(line["texto"])
        value = parse_price(line["texto"])
        if fuel:
            labels.append((fuel, x, y, line["confianza"]))
        if value is not None:
            prices.append((value, x, y, line["confianza"]))
    candidates = {}
    for value, x, y, confidence in prices:
        nearby = [(abs(x - lx) / width + abs(ly - y) / height, fuel, label_conf)
                  for fuel, lx, ly, label_conf in labels
                  if 0 < ly - y < height * 0.25 and abs(x - lx) < width * 0.075]
        nearby.sort()
        if not nearby or (len(nearby) > 1 and nearby[1][0] - nearby[0][0] < 0.02):
            continue
        _, fuel, label_conf = nearby[0]
        candidates.setdefault(fuel, []).append({"precio": str(value),
                                                "confianza": min(confidence, label_conf)})
    return {fuel: values[0] for fuel, values in candidates.items() if len(values) == 1}


def validate_candidate(fuel, observed_date, readings, today=None,
                       min_price=Decimal("10"), max_price=Decimal("80")):
    """Requiere dos vistas concordantes; estos controles no sustituyen evaluación humana."""
    reasons = []
    if fuel not in FUELS:
        reasons.append("COMBUSTIBLE_INVALIDO")
    if observed_date is None:
        reasons.append("FECHA_FALTANTE")
    elif observed_date > (today or date.today()):
        reasons.append("FECHA_FUTURA")
    values = []
    for reading in readings:
        try:
            value = Decimal(str(reading["precio"]))
            if not value.is_finite():
                raise InvalidOperation
            values.append(value)
        except (KeyError, InvalidOperation, ValueError):
            reasons.append("PRECIO_INVALIDO")
        if reading.get("confianza", 0) < 0.90:
            reasons.append("CONFIANZA_BAJA")
    if len(values) < 2:
        reasons.append("LECTURAS_INSUFICIENTES")
    if len(set(values)) > 1:
        reasons.append("VISTAS_DISCREPAN")
    if any(value < min_price or value > max_price for value in values):
        reasons.append("PRECIO_FUERA_RANGO")
    # Los límites son configurables: Q10-Q80 es un control amplio del piloto,
    # no una afirmación de que todos los precios históricos pertenezcan al rango.
    return list(dict.fromkeys(reasons))

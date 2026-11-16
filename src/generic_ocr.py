"""Extracción por etiquetas para surtidores que no usan la plantilla Shell."""
from datetime import datetime

import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from src.price_quality import FUELS,labelled_prices,validate_candidate

register_heif_opener()


def extract_labelled(source,source_uri,engine):
    with Image.open(source) as original:
        exif=original.getexif();detail=exif.get_ifd(34665)
        raw=detail.get(36867) or detail.get(36868) or exif.get(306)
        observed=datetime.strptime(str(raw)[:19],"%Y:%m:%d %H:%M:%S").date() if raw else None
        image=ImageOps.exif_transpose(original).convert("RGB")
    image.thumbnail((2600,2600))
    views=[(image,0),(image.crop((0,image.height//2,image.width,image.height)),image.height//2)]
    candidates=[]
    for view,offset in views:
        result,_=engine(np.array(view)[:,:,::-1].copy(),use_cls=False)
        lines=[{"texto":text,"confianza":float(score),"bbox":[[x,y+offset] for x,y in box]}
               for box,text,score in result or []]
        candidates.append(labelled_prices(lines,image.width,image.height,min_confidence=.85))
    results=[]
    for fuel in FUELS:
        readings=[view[fuel] for view in candidates if fuel in view]
        # La aceptación final mantiene confianza >=0.90 además de concordancia.
        reasons=validate_candidate(fuel,observed,readings)
        results.append({"foto_origen":source_uri,"fecha":observed.isoformat() if observed else None,
                        "combustible":fuel,"precio_q_galon":readings[0]["precio"] if readings and not reasons else None,
                        "estado":"candidato" if not reasons else "requiere_revision",
                        "plantilla":"etiquetas_explicitas","version_extractor":"labels-v2",
                        "motivos_revision":reasons,"lecturas":readings})
    return results

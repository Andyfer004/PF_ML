"""OCR de LCD rectificados para la plantilla Shell de cuatro combustibles."""
import io
import itertools
import re
import shutil
import subprocess
import json
import hashlib
import os
import csv
from pathlib import Path
from collections import Counter
from datetime import datetime
from decimal import Decimal

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from rapidocr_onnxruntime import RapidOCR

from src.price_quality import parse_price, identify_panel_fuels, transaction_unit_price, quarantine_review_flags
from src.photo_metadata import extract_metadata

register_heif_opener()
SLOTS = ("diesel", "regular", "super", "vpower")
VERSION = "lcd-consensus-labels-v3"


def ordered_box(points):
    points = np.asarray(points, dtype=np.float32)
    sums, differences = points.sum(axis=1), np.diff(points, axis=1).ravel()
    return points[[np.argmin(sums), np.argmin(differences), np.argmax(sums), np.argmax(differences)]]


def lcd_regions(rgb):
    """Busca cuatro LCD pequeños alineados; abstiene si no reconoce la plantilla."""
    bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    blue, green, red = [c.astype(np.int16) for c in cv2.split(bgr)]
    mask = ((blue - red > 6) & (blue > 125) & (green > 115)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                           np.ones((max(3, int(height * .009)), max(5, int(width * .020))), np.uint8))
    candidates = []
    dark = (cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) < 85).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    for source_mask in (mask, dark):
        contours = cv2.findContours(source_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if (.42 * height < y < .91 * height and .025 * width < w < .19 * width
                    and .008 * height < h < .09 * height and 1.3 < w / h < 8
                    and .00015 * width * height < area < .009 * width * height):
                candidates.append((contour, x, y, w, h, w*h, (x+w/2, y+h/2)))
    candidates = sorted(candidates, key=lambda c: -c[5])[:20]
    best, best_score = None, -float("inf")
    for group in itertools.combinations(candidates, 4):
        group = sorted(group, key=lambda c: c[6][0])
        xs, ys = np.array([c[6] for c in group]).T
        widths = np.array([c[3] for c in group])
        if xs[-1] - xs[0] < width * .22 or widths.max() / widths.min() > 2:
            continue
        gaps = np.diff(xs)
        if min(gaps) < np.median(widths) * 1.05 or max(gaps) > np.median(widths) * 4.5:
            continue
        fit = np.polyfit(xs, ys, 1)
        residual = np.max(np.abs(ys - np.polyval(fit, xs))) / height
        if residual > .015 or abs(fit[0]) > .65:
            continue
        score = sum(c[5] for c in group) / (height * width) - 2 * residual
        if score > best_score:
            best, best_score = group, score
    if best is None:
        return []
    regions = []
    for contour, x, y, w, h, area, center in best:
        center, size, angle = cv2.minAreaRect(contour)
        # Cerrar huecos de dígitos antes del rectángulo evita recortar el primer número.
        # minAreaRect puede devolver el lado corto primero: ampliar según su longitud.
        expansion = (2.25, 1.25) if size[0] < size[1] else (1.25, 2.25)
        rect = (center, (size[0] * expansion[0], size[1] * expansion[1]), angle)
        source = ordered_box(cv2.boxPoints(rect))
        actual_w = np.linalg.norm(source[1] - source[0])
        actual_h = np.linalg.norm(source[3] - source[0])
        out_h = max(90, min(240, round(512 * actual_h / actual_w)))
        destination = np.array([[0, 0], [511, 0], [511, out_h-1], [0, out_h-1]], np.float32)
        crop = cv2.warpPerspective(bgr, cv2.getPerspectiveTransform(source, destination), (512, out_h),
                                   flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        regions.append({"bbox": source.tolist(), "crop": crop})
    return regions


def normalized_price(text):
    # Solo espacios, no sustituciones de letras/dígitos ni puntos inventados.
    compact = re.sub(r"\s+", "", text)
    value = parse_price(compact)
    return str(value) if value is not None and 10 <= value <= 80 else None


class LCDExtractor:
    def __init__(self, tesseract=False, template_root=None, template_config=None):
        self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2,
                               det_limit_side_len=2000, det_limit_type="max", max_side_len=3000)
        self.tesseract = shutil.which("tesseract") if tesseract else None
        root = Path(__file__).resolve().parents[1]
        template_root = Path(template_root or root / "data/images")
        template_config = Path(template_config or root / "data/ocr_layout_templates.json")
        self.sift = cv2.SIFT_create(nfeatures=3000)
        self.line_cache = root / ".cache/ocr_lines"
        self.line_cache.mkdir(parents=True,exist_ok=True)
        flag_file=root/"data/ocr_review_flags.csv"
        self.review_flags={}
        if flag_file.exists():
            with flag_file.open(newline="") as stream:
                self.review_flags={(row["foto_origen"],row["combustible"]):row["motivo"] for row in csv.DictReader(stream)}
        self.templates = []
        if template_config.exists():
            for template in json.loads(template_config.read_text()):
                filename = template_root / template["archivo"]
                if not filename.exists():
                    continue
                with Image.open(filename) as image:
                    oriented = ImageOps.exif_transpose(image).convert("RGB")
                oriented.thumbnail((2600, 2600))
                gray = cv2.cvtColor(np.asarray(oriented), cv2.COLOR_RGB2GRAY)
                scale = np.array([oriented.width/template["base_size"][0], oriented.height/template["base_size"][1]])
                quads = np.array(template["digit_quads"], np.float32) * scale
                # Ajustar la homografía sobre el plano de etiquetas/LCD, excluyendo
                # el cuerpo central del surtidor que tiene otra profundidad.
                mask = np.zeros_like(gray)
                x0=max(0,int(quads[:,:,0].min()-oriented.width*.05));x1=min(oriented.width,int(quads[:,:,0].max()+oriented.width*.05))
                y0=max(0,int(quads[:,:,1].min()-oriented.height*.03))
                mask[y0:int(oriented.height*.94),x0:x1] = 255
                points, descriptors = self.sift.detectAndCompute(gray, mask)
                horizontal = (quads[:, 1] - quads[:, 0])[:, None, :]
                vertical = (quads[:, 3] - quads[:, 0])[:, None, :]
                quads = (quads + horizontal * np.array([-.16,.16,.16,-.16])[None,:,None]
                         + vertical * np.array([-.55,-.55,.18,.18])[None,:,None])
                self.templates.append((points, descriptors, quads))

    def matched_regions(self, image):
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
        mask = np.zeros_like(gray);mask[int(gray.shape[0]*.45):] = 255
        target_points, target_descriptors = self.sift.detectAndCompute(gray, mask)
        if target_descriptors is None:
            return []
        best, quality = [], 0
        matcher = cv2.BFMatcher(cv2.NORM_L2)
        for points, descriptors, quads in self.templates:
            pairs = matcher.knnMatch(descriptors, target_descriptors, k=2)
            matches = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .70*pair[1].distance]
            if len(matches) < 12:
                continue
            source = np.float32([points[m.queryIdx].pt for m in matches])
            target = np.float32([target_points[m.trainIdx].pt for m in matches])
            transform, inliers = cv2.findHomography(source, target, cv2.RANSAC, 4)
            if transform is None or int(inliers.sum()) < 10 or inliers.mean() < .4:
                continue
            # Exigir que los puntos de apoyo cubran el panel completo.
            support = source[inliers.ravel().astype(bool)]
            if np.ptp(support[:, 0]) < np.ptp(quads[:, :, 0]) * .65:
                continue
            mapped = cv2.perspectiveTransform(quads.reshape(-1, 1, 2).astype(np.float32), transform).reshape(4, 4, 2)
            if np.any(mapped < 0) or np.any(mapped[:, :, 0] >= image.width) or np.any(mapped[:, :, 1] >= image.height):
                continue
            if any(not cv2.isContourConvex(q.astype(np.float32)) or cv2.contourArea(q.astype(np.float32)) < 100 for q in mapped):
                continue
            if int(inliers.sum()) <= quality:
                continue
            regions = []
            for quad in mapped:
                width = np.linalg.norm(quad[1]-quad[0])
                height = np.linalg.norm(quad[3]-quad[0])
                out_h = max(90, min(220, int(512*height/width)))
                rectangle = np.float32([[0,0],[511,0],[511,out_h-1],[0,out_h-1]])
                crop = cv2.warpPerspective(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR),
                                           cv2.getPerspectiveTransform(quad.astype(np.float32), rectangle),
                                           (512,out_h), flags=cv2.INTER_CUBIC)
                regions.append({"bbox":quad.tolist(),"crop":crop,"digits_only":True})
            best, quality = regions, int(inliers.sum())
        return best

    def lines(self, bgr):
        key=hashlib.sha256(bgr.tobytes()+b"rapidocr1.4.4-det2000max-rec-no-cls").hexdigest()
        filename=self.line_cache/(key+".json")
        if filename.exists():
            return json.loads(filename.read_text())
        result,_=self.engine(bgr,use_cls=False)
        result=result or []
        temp=filename.with_suffix(f".{os.getpid()}.tmp")
        temp.write_text(json.dumps(result));temp.replace(filename)
        return result

    def read_crop(self, crop, digits_only=False):
        # El rectángulo incluye un margen de seguridad y el encabezado. Reconocer
        # directamente la banda numérica evita partir los dígitos en cajas de texto.
        h, w = crop.shape[:2]
        if not digits_only:
            crop = crop[int(h*.25):int(h*.72), int(w*.10):int(w*.90)]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        contrast = cv2.createCLAHE(clipLimit=2, tileGridSize=(4, 4)).apply(gray)
        attempts = []
        for name, image in (("color", crop), ("gris", gray), ("contraste", contrast)):
            padded = cv2.copyMakeBorder(image, 18, 18, 18, 18, cv2.BORDER_CONSTANT, value=255)
            result, _ = self.engine(padded, use_det=False, use_cls=False)
            # El detector puede separar el último dígito: concatenar solo sobre un mismo LCD.
            texts = [(str(line[0]), float(line[1])) for line in (result or [])]
            direct = [(normalized_price(text), confidence, text) for text, confidence in texts
                      if normalized_price(text) is not None]
            unique = {x[0] for x in direct}
            if len(unique) == 1:
                value, confidence, text = max(direct, key=lambda x: x[1])
            else:
                text = " | ".join(x[0] for x in texts)
                value, confidence = None, 0
            attempts.append({"motor": "rapidocr", "variante": name, "texto": text,
                             "precio": value, "confianza": confidence})
        if self.tesseract:
            for name, image in (("gris", gray), ("contraste", contrast)):
                ok, encoded = cv2.imencode(".png", image)
                completed = subprocess.run([self.tesseract, "stdin", "stdout", "--psm", "7", "-c",
                                            "tessedit_char_whitelist=0123456789."],
                                           input=encoded.tobytes(), capture_output=True, timeout=15, check=True)
                text = completed.stdout.decode().strip()
                attempts.append({"motor": "tesseract", "variante": name, "texto": text,
                                 "precio": normalized_price(text), "confianza": None})
        votes = Counter(a["precio"] for a in attempts if a["precio"] is not None
                        and (a["confianza"] is None or a["confianza"] >= .85))
        ranking = votes.most_common()
        accepted = bool(ranking and ranking[0][1] >= 2 and (len(ranking) == 1 or ranking[0][1] > ranking[1][1]))
        return {"precio": ranking[0][0] if accepted else None, "votos": dict(votes),
                "estado": "candidato" if accepted else "requiere_revision", "intentos": attempts}

    def extract(self, source, source_uri=None):
        payload=source.getvalue() if hasattr(source,"getvalue") else None
        with Image.open(io.BytesIO(payload) if payload is not None else source) as original:
            exif = original.getexif()
            detail = exif.get_ifd(34665)
            raw_date = detail.get(36867) or detail.get(36868) or exif.get(306)
            observed = datetime.strptime(str(raw_date)[:19], "%Y:%m:%d %H:%M:%S").date() if raw_date else None
            image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((2600, 2600))
        regions = self.matched_regions(image) or lcd_regions(image)
        spatial_readings = [[] for _ in regions]
        all_lines=[]
        if regions:
            for view_name, view, offset in (("completa", image, 0),
                                             ("inferior", image.crop((0,image.height//2,image.width,image.height)),image.height//2),
                                             ("precios", image.crop((0,int(image.height*.55),image.width,int(image.height*.9))),int(image.height*.55))):
                lines = self.lines(np.asarray(view)[:,:,::-1].copy())
                for box, text, confidence in lines:
                    all_lines.append({"texto":text,"confianza":float(confidence),
                                      "bbox":[[float(x),float(y)+offset] for x,y in box]})
                    value = normalized_price(text)
                    if value is None or confidence < .85:
                        continue
                    point = np.asarray(box).mean(axis=0) + np.array([0,offset])
                    options = []
                    for i,region in enumerate(regions):
                        quad = np.asarray(region["bbox"])
                        center = quad.mean(axis=0)
                        width = np.linalg.norm(quad[1]-quad[0])
                        height = np.linalg.norm(quad[3]-quad[0])
                        if abs(point[0]-center[0]) < width*.95 and abs(point[1]-center[1]) < image.height*.10:
                            options.append((abs(point[0]-center[0])/width,i))
                    if options:
                        _,i = min(options)
                        spatial_readings[i].append({"motor":"rapidocr_espacial","variante":view_name,
                                                    "texto":text,"precio":value,"confianza":float(confidence)})
        if not regions:
            from src.generic_ocr import extract_labelled
            cached_engine=lambda bgr,**kwargs:(self.lines(bgr),None)
            results=extract_labelled(io.BytesIO(payload) if payload is not None else source,source_uri or str(source),cached_engine)
            results=quarantine_review_flags(results,self.review_flags)
            return {"foto_origen":source_uri or str(source),"fecha":observed.isoformat() if observed else None,
                    "pantallas_detectadas":0,"resultados":results,"metodo":"etiquetas_genericas"}
        metadata=extract_metadata(all_lines)
        mapping=identify_panel_fuels(regions,all_lines,image.height)
        slot_readings=[]
        for index in range(len(regions)):
            reading = self.read_crop(regions[index]["crop"], regions[index].get("digits_only",False)) if len(regions) == 4 else {
                "precio": None, "votos": {}, "estado": "requiere_revision", "intentos": []}
            if regions:
                reading["intentos"].extend(spatial_readings[index])
                votes = Counter(a["precio"] for a in reading["intentos"] if a["precio"] is not None
                                and (a["confianza"] is None or a["confianza"] >= .85))
                ranking = votes.most_common()
                accepted = bool(ranking and ranking[0][1] >= 2 and (len(ranking)==1 or ranking[0][1] > ranking[1][1]))
                reading.update(precio=ranking[0][0] if accepted else None, votos=dict(votes),
                               estado="candidato" if accepted else "requiere_revision")
            slot_readings.append(reading)
        results=[]
        for fuel in SLOTS:
            index=next((i for i,name in mapping.items() if name==fuel),None)
            reading=slot_readings[index] if index is not None else {"precio":None,"estado":"requiere_revision","votos":{},"intentos":[]}
            results.append({"foto_origen": source_uri or str(source), "combustible": fuel,
                            "fecha": observed.isoformat() if observed else None,
                            "precio_q_galon": reading["precio"], "estado": reading["estado"],
                            "plantilla": "shell_4_lcd", "version_extractor": VERSION,
                            "motivos_revision": [] if reading["precio"] else ["SIN_CONSENSO" if index is not None else "COMBUSTIBLE_NO_IDENTIFICADO"],
                            "lectura": reading, "bbox": regions[index]["bbox"] if index is not None else None,**metadata})
        unit=transaction_unit_price(all_lines,image.height)
        if unit is not None:
            accepted=[parse_price(row["precio_q_galon"]) for row in results if row["precio_q_galon"]]
            if accepted and not any(abs(price-unit)<=Decimal(".03") for price in accepted):
                for row in results:
                    if row["precio_q_galon"]:
                        row["precio_sin_validar"]=row["precio_q_galon"]
                        row["precio_q_galon"]=None;row["estado"]="requiere_revision"
                        row["motivos_revision"].append("TRANSACCION_NO_COINCIDE_CON_LCD")
        results=quarantine_review_flags(results,self.review_flags)
        return {"foto_origen": source_uri or str(source), "fecha": observed.isoformat() if observed else None,
                "pantallas_detectadas": len(regions), "resultados": results,"etiquetas_paneles":mapping,
                "precio_unitario_transaccion":str(unit) if unit else None}

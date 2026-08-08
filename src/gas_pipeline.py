import argparse
import csv
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

if __package__:
    from .external_data import (
        ExternalContext,
        cargar_eventos,
        cargar_series_mercado,
        construir_contexto_externo,
        parse_exif_datetime,
        preparar_datos_externos,
    )
else:
    from external_data import (
        ExternalContext,
        cargar_eventos,
        cargar_series_mercado,
        construir_contexto_externo,
        parse_exif_datetime,
        preparar_datos_externos,
    )


register_heif_opener()
FUELS = ("diesel", "regular", "super", "vpower")
MATCH_TOLERANCE = 0.02


@dataclass
class ImageRecord:
    archivo: str
    ruta_imagen: str
    ruta_metadata_json: str
    fecha_original: str | None
    camara: str | None
    gps_lat: Any
    gps_lon: Any
    zona_horaria: str | None
    total_venta_manual: float | None
    galones_manual: float | None
    precio_diesel_imagen_manual: float | None
    precio_regular_imagen_manual: float | None
    precio_super_imagen_manual: float | None
    precio_vpower_imagen_manual: float | None
    precio_super_division: float | None
    precio_regular_estimado: float | None
    precio_vpower_estimado: float | None
    diferencia_regular: float | None
    diferencia_super: float | None
    diferencia_vpower: float | None
    regular_match_flag: int
    super_match_flag: int
    vpower_match_flag: int
    todos_match_flag: int
    estado_flag: str
    pantallas_inferiores_detectadas: int
    requiere_revision_flag: int
    fecha_mercado: str | None
    brent_usd_barril: float | None
    wti_usd_barril: float | None
    variacion_brent_7d_pct: float | None
    eventos_ventana_dias: int
    eventos_relevantes_cantidad: int
    evento_importante_flag: int
    tipos_evento: str
    impactos_evento: str
    eventos_resumen: str
    fuentes_eventos: str
    datos_externos_estado: str


def run_command(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Fallo el comando: {' '.join(command)}")
    return result.stdout


def obtener_metadata_completa(ruta_archivo: Path) -> dict[str, Any]:
    try:
        # -n conserva GPS y otros campos numericos como numeros en el JSON.
        return json.loads(run_command(["exiftool", "-j", "-n", str(ruta_archivo)]))[0]
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError):
        with Image.open(ruta_archivo) as image:
            exif = {
                str(key): str(value)
                for key, value in image.getexif().items()
            }
        stat = ruta_archivo.stat()
        return {
            "SourceFile": str(ruta_archivo.resolve()),
            "FileName": ruta_archivo.name,
            "FileSize": stat.st_size,
            "FileModifyDate": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "PillowEXIF": exif,
        }


def metadata_resumen(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "fecha_original": metadata.get("DateTimeOriginal") or metadata.get("CreateDate"),
        "camara": metadata.get("Model"),
        "gps_lat": metadata.get("GPSLatitude"),
        "gps_lon": metadata.get("GPSLongitude"),
        "zona_horaria": metadata.get("OffsetTimeOriginal"),
    }


def abrir_imagen_orientada(ruta_archivo: Path, max_width: int = 1600) -> Image.Image:
    with Image.open(ruta_archivo) as image:
        oriented = ImageOps.exif_transpose(image).convert("RGB")
    if oriented.width > max_width:
        ratio = max_width / oriented.width
        oriented = oriented.resize(
            (max_width, round(oriented.height * ratio)), Image.Resampling.LANCZOS
        )
    return oriented


def order_box_points(points: np.ndarray) -> np.ndarray:
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).ravel()
    return np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(differences)],
            points[np.argmax(sums)],
            points[np.argmax(differences)],
        ],
        dtype=np.float32,
    )


def detectar_pantallas_precios(image: Image.Image, output_dir: Path) -> dict[str, str]:
    """Detecta y rectifica los cuatro LCD inferiores usando solo OpenCV."""
    bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    blue, green, red = cv2.split(bgr)
    lcd_mask = (
        (blue.astype(np.int16) - red.astype(np.int16) > 8)
        & (blue > 140)
        & (green > 130)
    ).astype(np.uint8) * 255
    kernel = np.ones(
        (max(3, round(height * 0.003)), max(5, round(width * 0.0075))),
        dtype=np.uint8,
    )
    lcd_mask = cv2.morphologyEx(lcd_mask, cv2.MORPH_CLOSE, kernel)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(lcd_mask)

    candidates: list[tuple[int, int]] = []
    for label, (x, y, box_width, box_height, area) in enumerate(stats[1:], start=1):
        if not 0.60 * height < y < 0.78 * height:
            continue
        if not 0.025 * width < box_width < 0.10 * width:
            continue
        if not 0.012 * height < box_height < 0.04 * height:
            continue
        if area < 0.0002 * width * height:
            continue
        candidates.append((x, label))

    candidates.sort()
    if len(candidates) != 4:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = np.array([[0, 0], [319, 0], [319, 119], [0, 119]], dtype=np.float32)
    crops: dict[str, str] = {}
    for fuel, (_, label) in zip(FUELS, candidates):
        component = np.where(labels == label, 255, 0).astype(np.uint8)
        contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        center, size, angle = cv2.minAreaRect(contour)
        expanded_rect = (center, (size[0] * 1.4, size[1] * 1.5), angle)
        source = order_box_points(cv2.boxPoints(expanded_rect))
        transform = cv2.getPerspectiveTransform(source, destination)
        crop = cv2.warpPerspective(bgr, transform, (320, 120))
        crop_path = output_dir / f"{fuel}.png"
        cv2.imwrite(str(crop_path), crop)
        crops[fuel] = str(crop_path.resolve())
    return crops


def cargar_lecturas_manuales(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    readings: dict[str, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as csvfile:
        for row in csv.DictReader(csvfile):
            readings[row["archivo"]] = {
                key: float(row[key])
                for key in (
                    "total_venta",
                    "galones",
                    "precio_diesel",
                    "precio_regular",
                    "precio_super",
                    "precio_vpower",
                )
                if row.get(key)
            }
    return readings


def calcular_estimados(
    total: float | None, galones: float | None
) -> tuple[float | None, float | None, float | None]:
    if total is None or not galones:
        return None, None, None
    super_price = round(total / galones, 2)
    return round(super_price - 1.0, 2), super_price, round(super_price + 0.5, 2)


def comparar(precio_estimado: float | None, precio_manual: float | None) -> tuple[float | None, int]:
    if precio_estimado is None or precio_manual is None:
        return None, 0
    difference = round(precio_estimado - precio_manual, 2)
    return difference, int(abs(difference) <= MATCH_TOLERANCE)


def procesar_imagen(
    ruta_archivo: Path,
    readings: dict[str, dict[str, float]],
    output_dir: Path,
    external_context: ExternalContext,
) -> tuple[ImageRecord, dict[str, Any]]:
    complete_metadata = obtener_metadata_completa(ruta_archivo)
    metadata_path = output_dir / "metadata" / f"{ruta_archivo.stem}.json"
    exportar_json(complete_metadata, metadata_path)
    summary = metadata_resumen(complete_metadata)

    image = abrir_imagen_orientada(ruta_archivo)
    crop_paths = detectar_pantallas_precios(image, output_dir / "crops" / ruta_archivo.stem)
    manual = readings.get(ruta_archivo.name, {})
    total = manual.get("total_venta")
    gallons = manual.get("galones")
    diesel_manual = manual.get("precio_diesel")
    regular_manual = manual.get("precio_regular")
    super_manual = manual.get("precio_super")
    vpower_manual = manual.get("precio_vpower")

    regular_estimated, super_division, vpower_estimated = calcular_estimados(total, gallons)
    regular_difference, regular_flag = comparar(regular_estimated, regular_manual)
    super_difference, super_flag = comparar(super_division, super_manual)
    vpower_difference, vpower_flag = comparar(vpower_estimated, vpower_manual)
    all_flags = int(regular_flag == super_flag == vpower_flag == 1)
    complete_manual = all(
        value is not None
        for value in (total, gallons, diesel_manual, regular_manual, super_manual, vpower_manual)
    )
    review_flag = int(not complete_manual or len(crop_paths) != 4 or not all_flags)

    record = ImageRecord(
        archivo=ruta_archivo.name,
        ruta_imagen=str(ruta_archivo.relative_to(output_dir.parent)),
        ruta_metadata_json=str(metadata_path.relative_to(output_dir.parent)),
        **summary,
        total_venta_manual=total,
        galones_manual=gallons,
        precio_diesel_imagen_manual=diesel_manual,
        precio_regular_imagen_manual=regular_manual,
        precio_super_imagen_manual=super_manual,
        precio_vpower_imagen_manual=vpower_manual,
        precio_super_division=super_division,
        precio_regular_estimado=regular_estimated,
        precio_vpower_estimado=vpower_estimated,
        diferencia_regular=regular_difference,
        diferencia_super=super_difference,
        diferencia_vpower=vpower_difference,
        regular_match_flag=regular_flag,
        super_match_flag=super_flag,
        vpower_match_flag=vpower_flag,
        todos_match_flag=all_flags,
        estado_flag="ENCENDIDO" if all_flags else "APAGADO",
        pantallas_inferiores_detectadas=len(crop_paths),
        requiere_revision_flag=review_flag,
        **asdict(external_context),
    )
    detail = {
        "registro": asdict(record),
        "metadata_completa": str(metadata_path.resolve()),
        "pantallas_inferiores": crop_paths,
        "nota": "Los precios *_imagen_manual provienen de la lectura humana del LCD.",
    }
    return record, detail


def exportar_csv(records: list[ImageRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=list(asdict(records[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(record) for record in records)


def exportar_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepara imagenes y contexto del mercado de combustibles.")
    parser.add_argument(
        "--actualizar-externos",
        action="store_true",
        help="Vuelve a descargar las series internacionales aunque exista cache.",
    )
    args = parser.parse_args()
    base_dir = Path(__file__).resolve().parent.parent
    image_dir = base_dir / "data" / "images"
    output_dir = base_dir / "output"
    readings = cargar_lecturas_manuales(base_dir / "data" / "lecturas_manuales.csv")
    heic_files = sorted(image_dir.glob("*.HEIC"))
    if not heic_files:
        raise FileNotFoundError(f"No se encontraron HEIC en: {image_dir}")

    image_metadata = {path: obtener_metadata_completa(path) for path in heic_files}
    image_datetimes = {
        path: parse_exif_datetime(metadata_resumen(metadata)["fecha_original"])
        for path, metadata in image_metadata.items()
    }
    market_path = base_dir / "data" / "external" / "series_mercado.csv"
    acquisition_status = preparar_datos_externos(
        [value.date() for value in image_datetimes.values() if value],
        market_path,
        actualizar=args.actualizar_externos,
    )
    market = cargar_series_mercado(market_path)
    events = cargar_eventos(base_dir / "data" / "eventos_globales.csv")

    records: list[ImageRecord] = []
    for path in heic_files:
        image_date = image_datetimes[path].date() if image_datetimes[path] else None
        context = construir_contexto_externo(
            image_date, market, events, acquisition_status
        )
        record, detail = procesar_imagen(path, readings, output_dir, context)
        records.append(record)
        exportar_json(detail, output_dir / "records" / f"{path.stem}.json")

    records.sort(key=lambda item: item.fecha_original or "")
    output_csv = output_dir / "gas_prices.csv"
    exportar_csv(records, output_csv)
    print(f"Procesadas: {len(records)} imagenes")
    print(f"CSV generado en: {output_csv}")


if __name__ == "__main__":
    main()

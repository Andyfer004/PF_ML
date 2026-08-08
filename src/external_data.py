import csv
import io
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
MARKET_SERIES = {
    "brent_usd_barril": "DCOILBRENTEU",
    "wti_usd_barril": "DCOILWTICO",
}
EVENT_LOOKBACK_DAYS = 21


@dataclass(frozen=True)
class ExternalContext:
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


def parse_exif_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], pattern)
        except ValueError:
            continue
    return None


def _download_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "PF-ML/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _download_fred_series(series_id: str, start: date, end: date) -> dict[date, float]:
    query = urllib.parse.urlencode(
        {"id": series_id, "cosd": start.isoformat(), "coed": end.isoformat()}
    )
    rows = csv.DictReader(io.StringIO(_download_text(f"{FRED_CSV_URL}?{query}")))
    values: dict[date, float] = {}
    for row in rows:
        raw_value = row.get(series_id, "")
        if not raw_value or raw_value == ".":
            continue
        values[date.fromisoformat(row["observation_date"])] = float(raw_value)
    return values


def actualizar_series_mercado(start: date, end: date, output_path: Path) -> None:
    series = {
        column: _download_fred_series(series_id, start, end)
        for column, series_id in MARKET_SERIES.items()
    }
    all_dates = sorted(set().union(*(values.keys() for values in series.values())))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=["fecha", *MARKET_SERIES, "fuente"],
        )
        writer.writeheader()
        for observation_date in all_dates:
            writer.writerow(
                {
                    "fecha": observation_date.isoformat(),
                    **{
                        column: values.get(observation_date, "")
                        for column, values in series.items()
                    },
                    "fuente": FRED_CSV_URL,
                }
            )


def cargar_series_mercado(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    observations: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as csvfile:
        for row in csv.DictReader(csvfile):
            observations.append(
                {
                    "fecha": date.fromisoformat(row["fecha"]),
                    "brent_usd_barril": _optional_float(row.get("brent_usd_barril")),
                    "wti_usd_barril": _optional_float(row.get("wti_usd_barril")),
                }
            )
    return observations


def cargar_eventos(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    events: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as csvfile:
        for row in csv.DictReader(csvfile):
            if not row.get("fecha_inicio"):
                continue
            events.append(
                {
                    **row,
                    "fecha_inicio": date.fromisoformat(row["fecha_inicio"]),
                    "fecha_fin": date.fromisoformat(row["fecha_fin"])
                    if row.get("fecha_fin")
                    else date.fromisoformat(row["fecha_inicio"]),
                    "importancia": int(row.get("importancia", "0")),
                }
            )
    return events


def preparar_datos_externos(
    image_dates: list[date],
    market_path: Path,
    actualizar: bool = False,
) -> str:
    if not image_dates:
        return "SIN_FECHAS"
    if market_path.exists() and not actualizar:
        return "CACHE"
    start = min(image_dates) - timedelta(days=30)
    end = max(image_dates)
    try:
        actualizar_series_mercado(start, end, market_path)
        return "DESCARGADO"
    except (OSError, ValueError, csv.Error):
        return "CACHE_TRAS_ERROR" if market_path.exists() else "NO_DISPONIBLE"


def construir_contexto_externo(
    observation_date: date | None,
    market: list[dict[str, object]],
    events: list[dict[str, object]],
    acquisition_status: str,
) -> ExternalContext:
    if observation_date is None:
        return _empty_context("FECHA_IMAGEN_INVALIDA")

    current_market = _latest_market_value(market, observation_date)
    previous_market = _latest_market_value(market, observation_date - timedelta(days=7))
    brent = _market_float(current_market, "brent_usd_barril")
    previous_brent = _market_float(previous_market, "brent_usd_barril")
    variation = None
    if brent is not None and previous_brent:
        variation = round((brent / previous_brent - 1) * 100, 2)

    window_start = observation_date - timedelta(days=EVENT_LOOKBACK_DAYS)
    relevant_events = [
        event
        for event in events
        if event["fecha_inicio"] <= observation_date
        and event["fecha_fin"] >= window_start
    ]
    relevant_events.sort(key=lambda event: event["fecha_inicio"])
    return ExternalContext(
        fecha_mercado=current_market["fecha"].isoformat() if current_market else None,
        brent_usd_barril=brent,
        wti_usd_barril=_market_float(current_market, "wti_usd_barril"),
        variacion_brent_7d_pct=variation,
        eventos_ventana_dias=EVENT_LOOKBACK_DAYS,
        eventos_relevantes_cantidad=len(relevant_events),
        evento_importante_flag=int(any(event["importancia"] >= 3 for event in relevant_events)),
        tipos_evento=_join_unique(event["tipo_evento"] for event in relevant_events),
        impactos_evento=_join_unique(event["impacto_esperado"] for event in relevant_events),
        eventos_resumen=" | ".join(str(event["descripcion"]) for event in relevant_events),
        fuentes_eventos=_join_unique(event["fuente_url"] for event in relevant_events),
        datos_externos_estado=_external_status(acquisition_status, current_market, events),
    )


def _latest_market_value(
    market: list[dict[str, object]], cutoff: date
) -> dict[str, object] | None:
    candidates = [row for row in market if row["fecha"] <= cutoff]
    return max(candidates, key=lambda row: row["fecha"]) if candidates else None


def _market_float(row: dict[str, object] | None, key: str) -> float | None:
    if not row:
        return None
    value = row.get(key)
    return float(value) if value is not None else None


def _optional_float(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def _join_unique(values: object) -> str:
    return "|".join(dict.fromkeys(str(value) for value in values if value))


def _external_status(
    acquisition_status: str,
    market: dict[str, object] | None,
    events: list[dict[str, object]],
) -> str:
    missing = []
    if market is None:
        missing.append("MERCADO")
    if not events:
        missing.append("CATALOGO_EVENTOS")
    return acquisition_status if not missing else f"{acquisition_status};FALTA_{'_Y_'.join(missing)}"


def _empty_context(status: str) -> ExternalContext:
    return ExternalContext(
        fecha_mercado=None,
        brent_usd_barril=None,
        wti_usd_barril=None,
        variacion_brent_7d_pct=None,
        eventos_ventana_dias=EVENT_LOOKBACK_DAYS,
        eventos_relevantes_cantidad=0,
        evento_importante_flag=0,
        tipos_evento="",
        impactos_evento="",
        eventos_resumen="",
        fuentes_eventos="",
        datos_externos_estado=status,
    )

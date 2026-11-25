"""Clasificador semanal con etiquetas de calendario exactas y evaluación temporal."""
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

CLASSES = ["baja", "se_mantiene", "sube"]
NUMERIC_FEATURES = ["precio_promedio", "cambio_1w", "cambio_ultima_observacion",
                    "semanas_desde_ultima_observacion", "mes_sin", "mes_cos"]
FEATURES = ["combustible", *NUMERIC_FEATURES]


def today_gt():
    return datetime.now(ZoneInfo("America/Guatemala")).date()


def direction(change, threshold=0.10):
    # El redondeo monetario precede a la comparación para respetar los límites inclusivos.
    values = change.round(2)
    result = pd.Series(np.where(values > threshold, "sube",
                                np.where(values < -threshold, "baja", "se_mantiene")), index=change.index)
    return result.mask(values.isna())


def build_tables(observations, threshold=0.10, as_of=None, horizon_weeks=1):
    """Una fila por combustible/semana; nunca crea etiquetas a través de huecos.

    Oro representa la muestra de fotografías, no un promedio nacional. La cohorte
    de estaciones/modalidades debe validarse antes de interpretar variaciones.
    """
    if horizon_weeks not in (1, 2):raise ValueError('Horizonte permitido: una o dos semanas')
    frame = pd.DataFrame(observations).copy()
    if frame.empty:
        raise ValueError("No hay observaciones de precio aceptadas")
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="raise").dt.normalize()
    frame["precio_q_galon"] = pd.to_numeric(frame["precio_q_galon"], errors="raise")
    if not frame["combustible"].isin(["super", "regular", "diesel"]).all():
        raise ValueError("Combustible fuera del catálogo")
    if not np.isfinite(frame["precio_q_galon"]).all() or (frame["precio_q_galon"] <= 0).any():
        raise ValueError("Precio inválido")
    cutoff = pd.Timestamp(as_of or today_gt()).normalize()
    if (frame["fecha"] > cutoff).any():
        raise ValueError("Las observaciones incluyen fechas futuras")
    for column in ("ubicacion", "modalidad"):
        if column not in frame:
            frame[column] = "desconocida"
        frame[column] = frame[column].fillna("desconocida")
    key = ["fecha", "ubicacion", "modalidad", "combustible"]
    if (frame.groupby(key)["precio_q_galon"].nunique() > 1).any():
        raise ValueError("Precios en conflicto para una misma fecha/ubicación/modalidad/combustible")
    frame = frame.drop_duplicates(key)
    frame["semana"] = frame["fecha"] - pd.to_timedelta((frame["fecha"].dt.weekday - 1) % 7, unit="D")
    weekly = (frame.groupby(["semana", "combustible"], as_index=False)
              .agg(precio_promedio=("precio_q_galon", "mean"), precio_minimo=("precio_q_galon", "min"),
                   precio_maximo=("precio_q_galon", "max"), observaciones=("precio_q_galon", "size"),
                   ubicaciones=("ubicacion", "nunique")))
    # Las semanas abiertas sirven como información disponible para pronosticar;
    # jamás se consideran resultados observados completos para entrenar/evaluar.
    weekly["semana_cerrada"] = weekly["semana"] + pd.Timedelta(days=7) <= cutoff
    weekly = weekly.sort_values(["combustible", "semana"]).reset_index(drop=True)
    if not weekly["semana_cerrada"].any():
        raise ValueError("Todavía no hay semanas cerradas")
    previous = weekly[["semana", "combustible", "precio_promedio"]].copy()
    previous["semana"] += pd.Timedelta(days=7)
    previous = previous.rename(columns={"precio_promedio": "precio_anterior"})
    features = weekly.merge(previous, on=["semana", "combustible"], how="left", validate="one_to_one")
    features["cambio_1w"] = features["precio_promedio"] - features["precio_anterior"]
    features["variacion_pct"] = features["cambio_1w"] / features["precio_anterior"] * 100
    features["direccion"] = direction(features["cambio_1w"], threshold)
    features = features.sort_values(["combustible", "semana"]).reset_index(drop=True)
    grouped = features.groupby("combustible")
    features["cambio_ultima_observacion"] = grouped["precio_promedio"].diff()
    features["semanas_desde_ultima_observacion"] = grouped["semana"].diff().dt.days / 7
    # Si no hay cambio medible esta semana, la línea base conserva la última dirección conocida.
    features["baseline"] = features.groupby("combustible")["direccion"].ffill()
    features["mes_sin"] = np.sin(2 * np.pi * features["semana"].dt.month / 12)
    features["mes_cos"] = np.cos(2 * np.pi * features["semana"].dt.month / 12)
    # La etiqueta siempre es la dirección de la semana objetivo contra su semana
    # anterior exacta. Con horizonte 2 no se compara el precio objetivo con el de
    # hace dos semanas: eso sería otra variable distinta.
    future = features.loc[features['semana_cerrada'], ['semana','combustible','precio_promedio','direccion']].copy()
    future['semana'] -= pd.Timedelta(days=7*horizon_weeks)
    future = future.rename(columns={'precio_promedio':'precio_siguiente','direccion':'objetivo'})
    features = features.merge(future,on=['semana','combustible'],how='left',validate='one_to_one')
    features['semana_objetivo'] = features['semana'] + pd.Timedelta(days=7*horizon_weeks)
    supervised = features.dropna(subset=["objetivo", "baseline"]).copy()
    # Las únicas columnas de entrada son FEATURES; precio_siguiente y objetivo nunca entran al modelo.
    return weekly, features, supervised


def temporal_partition(dataset):
    weeks = sorted(dataset["semana_objetivo"].unique())
    if len(weeks) < 10:
        raise ValueError(f"Solo hay {len(weeks)} semanas objetivo evaluables; se requieren al menos 10")
    holdout = max(2, int(np.ceil(len(weeks) * 0.20)))
    train_weeks, validation_weeks, test_weeks = weeks[:-2*holdout], weeks[-2*holdout:-holdout], weeks[-holdout:]
    pieces = [dataset[dataset["semana_objetivo"].isin(part)].copy()
              for part in (train_weeks, validation_weeks, test_weeks)]
    # Purgar etiquetas que todavía no habrían cerrado al comenzar las features
    # del bloque siguiente, especialmente importante para horizonte de dos semanas.
    validation_limit = pieces[2]['semana'].min()
    pieces[1] = pieces[1][pieces[1]['semana_objetivo'] + pd.Timedelta(days=7) <= validation_limit].copy()
    if pieces[1].empty:raise ValueError('Validación insuficiente después de la purga temporal')
    train_limit = pieces[1]['semana'].min()
    pieces[0] = pieces[0][pieces[0]['semana_objetivo'] + pd.Timedelta(days=7) <= train_limit].copy()
    if len(pieces[0]) < 12 or pieces[0]["objetivo"].nunique() < 2:
        raise ValueError("Entrenamiento insuficiente: al menos 12 filas y dos clases")
    return pieces


def make_model(kind):
    numeric = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler())])
    preprocess = ColumnTransformer([
        ("numeric", numeric, NUMERIC_FEATURES),
        ("fuel", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["combustible"]),
    ])
    estimator = (LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=5)
                 if kind == "logistica" else
                 DecisionTreeClassifier(max_depth=3, min_samples_leaf=4, class_weight="balanced", random_state=5))
    return Pipeline([("features", preprocess), ("classifier", estimator)])


def metrics(actual, predicted):
    return {"accuracy": float(accuracy_score(actual, predicted)),
            "macro_f1": float(f1_score(actual, predicted, labels=CLASSES, average="macro", zero_division=0)),
            "matriz_confusion": confusion_matrix(actual, predicted, labels=CLASSES).tolist(),
            "clases": CLASSES, "n": len(actual)}


def train_predictor(observations, threshold=0.10, as_of=None, horizon_weeks=1):
    weekly, features, data = build_tables(observations, threshold, as_of, horizon_weeks)
    train, validation, test = temporal_partition(data)
    experiments, trained = {}, {}
    for kind in ("logistica", "arbol"):
        model = make_model(kind).fit(train[FEATURES], train["objetivo"])
        experiments[kind] = metrics(validation["objetivo"], model.predict(validation[FEATURES]))
        trained[kind] = model
    chosen = max(experiments, key=lambda name: experiments[name]["macro_f1"])
    # Elegir con validación; la prueba final se consulta una sola vez después de elegir.
    development = pd.concat([train, validation])
    evaluation_model = make_model(chosen).fit(development[FEATURES], development["objetivo"])
    predictions = evaluation_model.predict(test[FEATURES])
    report = {
        "modelo": chosen, "umbral_q": threshold, "horizonte_semanas": horizon_weeks,
        "version_validacion": "temporal_purgada_v2",
        "purga_temporal": "Etiquetas cerradas antes de la primera semana de features del bloque siguiente",
        "observaciones_semanales": len(weekly), "ejemplos_supervisados": len(data),
        "validacion_modelos": experiments,
        "modelo_test": metrics(test["objetivo"], predictions),
        "baseline_test": metrics(test["objetivo"], test["baseline"]),
        "por_combustible": {},
        "particiones": {},
        "clases_entrenamiento": sorted(development["objetivo"].unique().tolist()),
        "features": FEATURES,
    }
    for name, frame in (("entrenamiento", train), ("validacion", validation), ("prueba", test)):
        report["particiones"][name] = {
            "n": len(frame), "desde": frame["semana_objetivo"].min().date().isoformat(),
            "hasta": frame["semana_objetivo"].max().date().isoformat(),
            "semanas": frame["semana_objetivo"].nunique(),
        }
    test = test.copy()
    test["prediccion"] = predictions
    for fuel, group in test.groupby("combustible"):
        report["por_combustible"][fuel] = {
            "modelo": metrics(group["objetivo"], group["prediccion"]),
            "baseline": metrics(group["objetivo"], group["baseline"]),
        }
    report["supera_baseline_macro_f1"] = report["modelo_test"]["macro_f1"] > report["baseline_test"]["macro_f1"]
    # El modelo para emitir pronósticos utiliza todos los resultados ya conocidos.
    production_model = make_model(chosen).fit(data[FEATURES], data["objetivo"])
    production_model.evaluation_model_ = evaluation_model
    production_model.horizon_weeks_ = horizon_weeks
    report["modelo_produccion_reentrenado_con_historial_completo"] = True
    return production_model, report, {"precio_semanal": weekly, "features_modelo": features,
                                      "evaluacion_temporal": test}


def historical_predictions(model, report, tables, generated_at):
    """Reconstruye la prueba reservada con el modelo previo a ella, no el reajustado."""
    if report['horizonte_semanas'] != 1:
        raise ValueError('La demostración histórica exige horizonte de una semana')
    test=tables['evaluacion_temporal']
    trained_until=max(pd.Timestamp(report['particiones'][name]['hasta'])
                      for name in ('entrenamiento','validacion'))+pd.Timedelta(days=6)
    if not (trained_until < test['semana']).all():
        raise ValueError('El modelo histórico conoce etiquetas posteriores al inicio de prueba')
    evaluated=model.evaluation_model_
    probabilities=evaluated.predict_proba(test[FEATURES])
    predictions=evaluated.predict(test[FEATURES])
    rows=[]
    for row, label, scores in zip(test.itertuples(),predictions,probabilities):
        target=pd.Timestamp(row.semana_objetivo)
        if target-pd.Timestamp(row.semana)!=pd.Timedelta(days=7):
            raise ValueError('La semana objetivo debe seguir exactamente a la semana de datos')
        index=list(evaluated.classes_).index(label)
        rows.append({'semana':target.date().isoformat(),'combustible':row.combustible,
            'semana_datos':row.semana.date().isoformat(),
            'fecha_corte_simulada':(target-pd.Timedelta(days=1)).date().isoformat(),
            'entrenamiento_hasta':trained_until.date().isoformat(),
            'generado_el':generated_at,'modo':'evaluacion_historica','horizonte_semanas':1,
            'prediccion':str(label),'probabilidad':float(scores[index]),
            'direccion_real':row.objetivo,'baseline':row.baseline,
            'acierto':bool(label==row.objetivo),'baseline_acierto':bool(row.baseline==row.objetivo),
            'precio_semana_base':float(row.precio_promedio),
            'precio_semana_objetivo':float(row.precio_siguiente),
            'variacion_real_q':float(round(row.precio_siguiente-row.precio_promedio,2))})
    return rows


def forecast(model, features, as_of=None):
    """Emite únicamente objetivos que todavía no han empezado; avisa ante historia atrasada."""
    cutoff = pd.Timestamp(as_of or today_gt()).normalize()
    latest = features.sort_values("semana").groupby("combustible").tail(1).copy()
    horizon=int(getattr(model,"horizon_weeks_",1))
    if not ((features["semana_objetivo"]-features["semana"]).dt.days == 7*horizon).all():
        raise ValueError("Las features no corresponden al horizonte del modelo")
    available = latest[latest["semana_objetivo"] > cutoff].copy()
    blocked = [{"combustible": row.combustible, "ultima_semana": row.semana.date().isoformat(),
                "motivo": "FALTA_PRECIO_DE_LA_SEMANA_RECIENTE"}
               for row in latest[latest["semana_objetivo"] <= cutoff].itertuples()]
    result = []
    if not available.empty:
        probability = model.predict_proba(available[FEATURES])
        labels = model.classes_
        for row, probabilities in zip(available.itertuples(), probability):
            i = int(np.argmax(probabilities))
            result.append({"combustible": row.combustible, "semana": row.semana_objetivo.date().isoformat(),
                           "semana_datos": row.semana.date().isoformat(), "prediccion": str(labels[i]),
                           "probabilidad": float(probabilities[i]), "direccion_real": None,
                           "fecha_emision": cutoff.date().isoformat(),
                           "semana_base_cerrada": bool(row.semana_cerrada),
                           "observaciones_semana_base": int(row.observaciones),
                           "horizonte_semanas": int(getattr(model,"horizon_weeks_",1)),
                           "antiguedad_datos_dias": int((cutoff-row.semana).days)})
    return result, blocked


def horizon_for_next_week(observations,as_of=None):
    """Usa horizonte 2 solo si los tres combustibles requieren el mismo rezago.

    El calendario objetivo es el próximo martes. Si la historia es más antigua
    conserva horizonte 1 para que forecast bloquee, sin extrapolar sin límite.
    """
    cutoff=pd.Timestamp(as_of or today_gt()).normalize()
    target=cutoff+pd.Timedelta(days=(1-cutoff.weekday())%7 or 7)
    frame=pd.DataFrame(observations)
    if frame.empty:return 1
    observed=pd.to_datetime(frame['fecha']).dt.normalize()
    weeks=observed-pd.to_timedelta((observed.dt.weekday-1)%7,unit='D')
    latest=frame.assign(semana=weeks).groupby('combustible')['semana'].max()
    gaps=((target-latest).dt.days//7).tolist()
    return 2 if len(gaps)==3 and all(g==2 for g in gaps) else 1

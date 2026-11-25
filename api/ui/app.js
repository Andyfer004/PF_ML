/* Dashboard de lectura. Todas las cifras vienen de la API o de evidencia fechada. */
"use strict";

const FUELS = {
  super: { name: "Súper", color: "#5270ee", soft: "#eef1ff" },
  regular: { name: "Regular", color: "#b98227", soft: "#fff7e8" },
  diesel: { name: "Diésel", color: "#299b8f", soft: "#eaf7f4" },
};
const VIEWS = {
  resumen: [
    "Resumen",
    "COMBUSTIBLES EN GUATEMALA",
    "Precios y predicciones",
    "Referencia MEM para ciudad capital, fotografías del curso y resultados del modelo.",
  ],
  historico: [
    "Histórico",
    "LA HISTORIA DEL PRECIO",
    "Histórico de combustibles",
    "Compara el precio semanal de súper, regular y diésel en quetzales por galón.",
  ],
  predicciones: [
    "Predicciones",
    "EL MODELO EN CONTEXTO",
    "Evalúa las predicciones",
    "Consulta una semana de prueba histórica o el pronóstico vigente.",
  ],
  pipeline: [
    "Pipeline y OCR",
    "DE LA FOTO AL DATO",
    "El trabajo detrás del precio",
    "Ingesta, extracción, controles de calidad y evidencia de la última validación.",
  ],
  api: [
    "Probar la API",
    "EXPLORADOR DE ENDPOINTS",
    "Consulta los datos directamente",
    "Haz una petición real y revisa su respuesta, código HTTP y tiempo de ejecución.",
  ],
};
const ENDPOINTS = {
  "/health": "Estado y publicación disponible",
  "/precios/actual": "Último precio por combustible",
  "/precios": "Histórico semanal con filtros",
  "/prediccion": "Evaluación histórica o pronóstico vigente",
  "/prediccion/historica": "Evaluación histórica con resultado real",
  "/prediccion/historica/semanas": "Semanas disponibles para evaluar",
  "/modelo/metricas": "Modelo frente a la línea base",
  "/proyecto/resumen": "Resumen verificado del proyecto",
};
const state = {
  view: VIEWS[location.hash.slice(1)] ? location.hash.slice(1) : "resumen",
  source: "mem",
  predictionMode: "historica",
  historicalWeek: "",
  historicalWeeks: null,
  range: 12,
  selected: new Set(Object.keys(FUELS)),
  showTable: false,
  loading: true,
  health: null,
  current: null,
  metrics: null,
  summary: null,
  predictions: {},
  history: null,
  requestId: 0,
  historyRequestId: 0,
  controller: null,
  explorer: {
    endpoint: "/health",
    fuel: "super",
    source: "",
    from: "",
    until: "",
    limit: "5",
    offset: "0",
    week: "",
    mode: "historica",
    result: null,
    busy: false,
  },
};
let chartObserver = null;
let toastTimer = null;
const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ],
  );
const icon = (name, extra = "") =>
  `<svg class="icon ${extra}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const number = (value, digits = 0) =>
  Number.isFinite(Number(value)) && value !== null && value !== ""
    ? Number(value).toLocaleString("es-GT", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
    : "—";
const percent = (value, digits = 1) =>
  value === undefined || value === null
    ? "—"
    : `${number(Number(value) * 100, digits)}%`;
const money = (value) => `Q${number(value, 2)}`;
const isoDate = (value) =>
  typeof value === "string" ? value.slice(0, 10) : "";
function dateLabel(value, year = false) {
  const input = isoDate(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input)) return "—";
  return new Intl.DateTimeFormat("es-GT", {
    day: "numeric",
    month: "short",
    ...(year ? { year: "numeric" } : {}),
    timeZone: "UTC",
  }).format(new Date(`${input}T12:00:00Z`));
}
function duration(seconds) {
  if (seconds < 60) return `${number(seconds)} s`;
  return `${Math.floor(seconds / 60)} min ${seconds % 60 ? `${seconds % 60} s` : ""}`.trim();
}
function todayGT() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Guatemala",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  return ["year", "month", "day"]
    .map((type) => parts.find((part) => part.type === type).value)
    .join("-");
}
function nextTuesday() {
  const date = new Date(`${todayGT()}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + ((2 - date.getUTCDay() + 7) % 7 || 7));
  return date.toISOString().slice(0, 10);
}
function errorMessage(result) {
  const detail = result?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.mensaje) return detail.mensaje;
  if (Array.isArray(detail))
    return "La API rechazó uno de los parámetros de la consulta.";
  return result?.status
    ? `La API respondió HTTP ${result.status}.`
    : "No se pudo conectar con la API.";
}
function emptyState(title, description, name = "info") {
  return `<div class="empty-state">${icon(name)}<strong>${escapeHTML(title)}</strong><p>${escapeHTML(description)}</p></div>`;
}
function direction(prediction) {
  const names = {
    baja: ["Baja", "down", ""],
    sube: ["Sube", "up", "up"],
    se_mantiene: ["Se mantiene", "flat", "flat"],
  };
  return names[prediction] || ["Sin pronóstico", "clock", "unavailable"];
}
function badge(prediction) {
  const [name, symbol, className] = direction(prediction);
  return `<span class="direction ${className}">${icon(symbol)}${name}</span>`;
}
function fuelStyle(fuel) {
  return `--fuel:${FUELS[fuel].color};--fuel-soft:${FUELS[fuel].soft}`;
}
function currentRows() {
  return state.current?.ok && Array.isArray(state.current.data.datos)
    ? state.current.data.datos
    : [];
}
function metrics() {
  return state.metrics?.ok ? state.metrics.data : null;
}
function summary() {
  return state.summary?.ok ? state.summary.data : null;
}
function forecast(fuel) {
  return state.predictions[fuel]?.ok ? state.predictions[fuel].data : null;
}
function historyRows() {
  return state.history?.ok && Array.isArray(state.history.data.datos)
    ? state.history.data.datos
        .filter((row) => state.selected.has(row.combustible))
        .sort((a, b) => a.semana.localeCompare(b.semana))
    : [];
}

async function request(path, signal) {
  const started = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch(path, {
      signal: controller.signal,
      cache: "no-store",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    const text = await response.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { mensaje: text.slice(0, 10000) };
    }
    return {
      path,
      status: response.status,
      ok: response.ok,
      data,
      elapsed: Math.round(performance.now() - started),
    };
  } catch (error) {
    return {
      path,
      status: 0,
      ok: false,
      data: {
        detail: {
          mensaje:
            error.name === "AbortError"
              ? "La consulta se canceló o excedió 25 segundos."
              : "No se pudo conectar con la API.",
        },
      },
      elapsed: Math.round(performance.now() - started),
    };
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}
function historyPath() {
  const weeks = currentRows()
    .map((row) => isoDate(row.semana))
    .filter(Boolean)
    .sort();
  const last = weeks.at(-1) || todayGT();
  const from = new Date(`${last}T12:00:00Z`);
  from.setUTCDate(from.getUTCDate() - (state.range - 1) * 7);
  return (
    "/precios?" +
    new URLSearchParams({
      fuente: state.source,
      desde: from.toISOString().slice(0, 10),
      hasta: last,
      limit: "1000",
    })
  );
}
async function loadData() {
  const id = ++state.requestId;
  state.controller?.abort();
  state.controller = new AbortController();
  const signal = state.controller.signal;
  const refresh = $("#refresh-button");
  refresh.disabled = true;
  refresh.classList.add("spinning");
  $("#service-status").className = "service-status loading";
  $("#service-status").innerHTML =
    '<span class="status-dot"></span>Consultando la API';
  const paths = [
    "/health",
    `/precios/actual?fuente=${state.source}`,
    `/modelo/metricas?fuente=${state.source}`,
    "/proyecto/resumen",
    `/prediccion/historica/semanas?fuente=${state.source}`,
  ];
  const results = await Promise.all(paths.map((path) => request(path, signal)));
  if (id !== state.requestId) return;
  [state.health, state.current, state.metrics, state.summary] = results;
  state.historicalWeeks = results[4];
  const weeks = results[4]?.ok ? results[4].data.datos : [];
  if (!weeks.some((row) => row.semana === state.historicalWeek))
    state.historicalWeek = results[4]?.data?.semana_predeterminada || "";
  const predictionResults = await Promise.all(Object.keys(FUELS).map((fuel) => {
    const query = new URLSearchParams({combustible: fuel, fuente: state.source});
    query.set("modo",state.predictionMode);
    if (state.predictionMode === "historica" && state.historicalWeek) query.set("semana", state.historicalWeek);
    return request("/prediccion?" + query, signal);
  }));
  if (id !== state.requestId) return;
  Object.keys(FUELS).forEach((fuel, index) => {
    state.predictions[fuel] = predictionResults[index];
  });
  const historyId = ++state.historyRequestId;
  const historical = await request(historyPath(), signal);
  if (id !== state.requestId) return;
  if (historyId === state.historyRequestId) state.history = historical;
  state.loading = false;
  refresh.disabled = false;
  refresh.classList.remove("spinning");
  $("#last-refresh").textContent =
    "Consulta: " +
    new Intl.DateTimeFormat("es-GT", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "America/Guatemala",
    }).format(new Date()) +
    " · Guatemala";
  render();
}
async function loadHistory() {
  const id = state.requestId;
  const historyId = ++state.historyRequestId;
  const historical = await request(historyPath(), state.controller?.signal);
  if (id !== state.requestId || historyId !== state.historyRequestId) return;
  state.history = historical;
  render();
}

function renderFuelCards() {
  return `<div class="fuel-grid">${Object.entries(FUELS)
    .map(([fuel, info]) => {
      const row = currentRows().find((record) => record.combustible === fuel);
      const prediction = forecast(fuel);
      return `<article class="fuel-card" style="${fuelStyle(fuel)}">
      <div class="fuel-heading"><span class="fuel-label"><span class="fuel-icon">${icon("pump")}</span>${info.name}</span><span class="fuel-tag">${state.source === "mem" ? "MEM" : "FOTOS"}</span></div>
      <div class="fuel-price"><span class="currency">Q</span><span class="amount">${row ? number(row.precio_promedio, 2) : "—"}</span><span class="unit">/ galón</span></div>
      <p class="fuel-date">${row ? `Semana del ${dateLabel(row.semana, true)}` : "Sin precio disponible"}</p>
      <div class="fuel-footer"><span class="caption">${state.predictionMode === "historica" ? "Prueba histórica" : "Próxima semana"}</span>${badge(prediction?.prediccion)}<span class="fuel-probability" title="Probabilidad asignada por el modelo a esta clase">${prediction ? percent(prediction.probabilidad) : "—"}</span></div>
    </article>`;
    })
    .join("")}</div>`;
}
function chartPanel(full = false) {
  const data = historyRows();
  const start = data[0]?.semana;
  const end = data.at(-1)?.semana;
  return `<section class="panel"><div class="panel-heading"><div><h2 class="panel-title">${full ? "Evolución del precio semanal" : "El precio a través del tiempo"}</h2><p class="panel-subtitle">Promedio por combustible · Q/galón</p></div>${full ? "" : '<a href="#historico" class="button button-quiet">Explorar histórico</a>'}</div>
    <div class="chart-controls"><div class="legend" role="group" aria-label="Combustibles de la gráfica">${Object.entries(
      FUELS,
    )
      .map(
        ([fuel, info]) =>
          `<button type="button" data-fuel-toggle="${fuel}" style="${fuelStyle(fuel)}" aria-pressed="${state.selected.has(fuel)}"><span class="legend-dot"></span>${info.name}</button>`,
      )
      .join(
        "",
      )}</div><div class="range-picker" role="group" aria-label="Periodo de la gráfica">${[
      [12, "12 semanas"],
      [26, "6 meses"],
      [52, "1 año"],
    ]
      .map(
        ([value, label]) =>
          `<button type="button" data-range="${value}" class="${state.range === value ? "active" : ""}" aria-pressed="${state.range === value}">${label}</button>`,
      )
      .join("")}</div></div>
    <div class="chart-wrap" id="chart-wrap">${data.length ? '<svg class="price-chart" id="price-chart" role="img" aria-label="Histórico semanal de precios en quetzales por galón"></svg><div id="chart-tooltip" class="chart-tooltip" hidden></div>' : emptyState("No hay datos para graficar", state.history?.ok ? "No se encontraron precios en este periodo." : errorMessage(state.history), "chart")}</div>
    <div class="chart-foot"><span>${data.length ? `${dateLabel(start, true)} — ${dateLabel(end, true)}` : "Sin observaciones"} · ${state.source === "mem" ? "MEM · ciudad capital" : "Fotografías"}</span>${full ? "" : `<button type="button" id="toggle-table" aria-expanded="${state.showTable}">${state.showTable ? "Ocultar tabla" : "Ver tabla de datos"}</button>`}</div>
    ${(full || state.showTable) && data.length ? renderHistoryTable(data) : ""}</section>`;
}
function renderHistoryTable(rows) {
  const sorted = [...rows].sort(
    (a, b) =>
      b.semana.localeCompare(a.semana) ||
      a.combustible.localeCompare(b.combustible),
  );
  return `<div class="table-scroll history-table"><table class="data-table"><thead><tr><th>Semana</th><th>Combustible</th><th>Promedio</th><th>Mínimo</th><th>Máximo</th><th>Observaciones</th></tr></thead><tbody>${sorted.map((row) => `<tr><td>${dateLabel(row.semana, true)}</td><td>${FUELS[row.combustible]?.name || escapeHTML(row.combustible)}</td><td class="number">${money(row.precio_promedio)}</td><td class="number">${money(row.precio_minimo)}</td><td class="number">${money(row.precio_maximo)}</td><td class="number">${number(row.observaciones)}</td></tr>`).join("")}</tbody></table></div><div class="table-caption">${number(rows.length)} registros en el periodo. Las semanas sin observaciones permanecen ausentes.</div>`;
}
function predictionPanel() {
  const target =
    Object.keys(FUELS).map(forecast).find(Boolean)?.semana || (state.predictionMode === "historica" ? state.historicalWeek : nextTuesday());
  return `<section class="panel"><div class="panel-heading"><div><h2 class="panel-title">${state.predictionMode === "historica" ? "Evaluación histórica" : "La próxima semana"}</h2><p class="panel-subtitle">${target ? `Semana del ${dateLabel(target, true)}` : "Sin semana evaluada disponible"}</p></div><a class="button button-quiet" href="#predicciones">Ver modelo</a></div><div class="prediction-list">${Object.entries(
    FUELS,
  )
    .map(([fuel, info]) => {
      const p = forecast(fuel);
      return `<div class="prediction-row"><span class="prediction-name" style="${fuelStyle(fuel)}"><span class="legend-dot"></span>${info.name}</span><div class="prediction-detail">${badge(p?.prediccion)}<span class="probability">${p ? percent(p.probabilidad) : "—"}</span></div></div>`;
    })
    .join(
      "",
    )}</div><div class="panel-note">${state.predictionMode === "historica" ? "Prueba reservada: compara la predicción con el resultado real en «Ver modelo»." : "El pronóstico depende de la disponibilidad de datos recientes."}</div></section>`;
}
function metricsPanel() {
  const m = metrics();
  return `<section class="panel"><div class="panel-heading"><div><h2 class="panel-title">¿Cómo se compara el modelo?</h2><p class="panel-subtitle">Exactitud en prueba temporal${m ? ` · ${number(m.n_prueba)} casos` : ""}</p></div></div>${m ? `<div class="metric-comparison"><div class="metric-row"><div class="metric-row-top"><span>Modelo de clasificación</span><strong>${percent(m.accuracy)}</strong></div><div class="metric-track"><div class="metric-fill" style="width:${Math.max(0, Math.min(100, Number(m.accuracy) * 100))}%"></div></div></div><div class="metric-row"><div class="metric-row-top"><span>Línea base</span><strong>${percent(m.baseline_accuracy)}</strong></div><div class="metric-track"><div class="metric-fill baseline" style="width:${Math.max(0, Math.min(100, Number(m.baseline_accuracy) * 100))}%"></div></div></div><div class="f1">Macro F1: <strong>${number(m.macro_f1, 3)}</strong> modelo / <strong>${number(m.baseline_macro_f1, 3)}</strong> línea base.<br>${Number(m.macro_f1) > Number(m.baseline_macro_f1) ? "El modelo supera la línea base en macro F1." : "El modelo queda por debajo de la línea base en macro F1."}</div></div>` : emptyState("Sin métricas disponibles", errorMessage(state.metrics))}</section>`;
}
function pipelineInline() {
  const s = summary();
  if (!s) return "";
  return `<section class="panel overview-pipeline"><div class="panel-heading"><div><h2 class="panel-title">Una validación de punta a punta</h2><p class="panel-subtitle">${number(s.datos.fotos)} fotos · ${number(s.pipeline.ejecuciones_validadas)} ejecuciones validadas · ${dateLabel(s.verificado_el, true)}</p></div><a href="#pipeline" class="button button-quiet">Ver proceso</a></div><div class="pipeline-inline">${s.pipeline.tareas.map((task, index) => `${index ? '<div class="pipeline-connector"></div>' : ""}<div class="pipeline-step"><span class="step-check">${icon("check")}</span><div><div class="step-name">${{ bronze: "Bronce", silver: "Plata", gold: "Oro" }[task.capa]}</div><div class="step-time">${duration(task.duracion_segundos)} · correcto</div></div></div>`).join("")}</div></section>`;
}
function overview() {
  return (
    renderFuelCards() +
    `<div class="dashboard-grid"><div>${chartPanel()}</div><div class="stack">${predictionPanel()}${metricsPanel()}</div></div>` +
    pipelineInline()
  );
}
function predictionControls() {
  const historical=state.predictionMode === "historica";
  const weeks=state.historicalWeeks?.ok ? state.historicalWeeks.data.datos : [];
  return `<section class="panel section-space"><div class="panel-body prediction-controls"><div class="field"><label for="prediction-mode">Qué quieres consultar</label><select id="prediction-mode"><option value="historica"${historical ? " selected" : ""}>Evaluación histórica</option><option value="vigente"${!historical ? " selected" : ""}>Pronóstico vigente</option></select></div>${historical ? `<div class="field"><label for="historical-week">Semana objetivo evaluada</label><select id="historical-week">${weeks.length ? weeks.map(row => `<option value="${escapeHTML(row.semana)}"${row.semana===state.historicalWeek ? " selected" : ""}>${dateLabel(row.semana,true)}${row.tres_combustibles ? " · 3 combustibles" : " · datos parciales"}</option>`).join("") : '<option value="">Sin semanas evaluadas</option>'}</select></div>` : ""}</div><div class="panel-note">${historical ? "Demostración con datos históricos: el modelo se entrenó antes de las semanas de prueba. La fecha de corte es simulada y se compara con un resultado posterior conocido. No es un pronóstico actual." : "Pronóstico para la próxima semana de calendario. Requiere precios recientes; si faltan, la API lo informa."}</div></section>`;
}
function historicalResult(p) {
  return `<div class="historical-result"><div class="metadata-row"><span>Resultado real</span>${badge(p.direccion_real)}</div><div class="metadata-row"><span>Modelo</span><strong>${p.acierto ? "Acertó" : "No acertó"}</strong></div><div class="metadata-row"><span>Línea base</span>${badge(p.baseline)}</div><div class="metadata-row"><span>Línea base vs. realidad</span><strong>${p.baseline_acierto ? "Acertó" : "No acertó"}</strong></div><div class="metadata-row"><span>Precio base / objetivo</span><strong>${money(p.precio_semana_base)} / ${money(p.precio_semana_objetivo)}</strong></div><div class="metadata-row"><span>Entrenamiento hasta</span><strong>${dateLabel(p.entrenamiento_hasta,true)}</strong></div><div class="metadata-row"><span>Generado realmente</span><strong>${dateLabel(p.generado_el,true)}</strong></div></div>`;
}
function predictionsView() {
  const m = metrics();
  return `<div class="fuel-grid prediction-grid">${Object.entries(FUELS)
    .map(([fuel, info]) => {
      const p = forecast(fuel);
      const [name, symbol, className] = direction(p?.prediccion);
      return `<article class="panel prediction-card" style="${fuelStyle(fuel)}"><div class="fuel-heading"><span class="fuel-label"><span class="fuel-icon">${icon("pump")}</span>${info.name}</span></div>${p ? `<p class="forecast-date">Semana del ${dateLabel(p.semana, true)}</p><div class="prediction-class ${className}">${icon(symbol)}${name}</div><div class="probability-large">${percent(p.probabilidad)}</div><div class="probability-label">Probabilidad asignada a esta clase</div><div class="prediction-metadata"><div class="metadata-row"><span>Datos de la semana</span><strong>${dateLabel(p.semana_datos, true)}</strong></div><div class="metadata-row"><span>${state.predictionMode === "historica" ? "Corte simulado" : "Emisión"}</span><strong>${dateLabel(p.fecha_corte_simulada || p.fecha_emision, true)}</strong></div><div class="metadata-row"><span>Horizonte</span><strong>${number(p.horizonte_semanas)} ${p.horizonte_semanas === 1 ? "semana" : "semanas"}</strong></div></div>${state.predictionMode === "historica" ? historicalResult(p) : ""}` : emptyState(state.predictionMode === "historica" ? "Sin evaluación histórica" : "Sin pronóstico vigente", errorMessage(state.predictions[fuel]), "clock")}</article>`;
    })
    .join(
      "",
    )}</div><div class="notice notice-info">${icon("info")}<span>El modelo clasifica <strong>sube, baja o se mantiene</strong>. Sus probabilidades no están calibradas y no garantizan aciertos. Una variación de hasta ±Q0.10 se clasifica como «se mantiene».</span></div><div class="dashboard-grid">${metricsPanel()}<section class="panel"><div class="panel-heading"><div><h2 class="panel-title">Una evaluación con orden temporal</h2><p class="panel-subtitle">Entrenamiento, validación y prueba en semanas diferentes</p></div></div><div class="model-facts"><div class="model-fact"><strong>${m ? number(m.n_prueba) : "—"}</strong><span>casos de prueba</span></div><div class="model-fact"><strong>${m ? number(m.horizonte_semanas) : "—"}</strong><span>semanas de horizonte</span></div><div class="model-fact"><strong>${state.source === "mem" ? "MEM" : "OCR"}</strong><span>fuente independiente</span></div></div><div class="panel-body"><ul class="rule-list"><li>${icon("check")}Las etiquetas de un bloque cierran antes de empezar el siguiente.</li><li>${icon("check")}El modelo se elige con validación y se compara en una prueba reservada.</li><li>${icon("check")}La línea base repite la última dirección conocida.</li></ul></div></section></div>${m && m.n_prueba < 30 ? '<div class="notice section-space">' + icon("warning") + "<span>La evaluación de fotografías tiene una muestra muy pequeña. Su desempeño es experimental.</span></div>" : ""}`;
}
function orchestrationPanel() {
  const proof=summary()?.orquestacion;
  if (!proof) return "";
  return `<section class="panel section-space" id="orquestacion-ejecuciones"><div class="panel-heading"><div><h2 class="panel-title">Dos semanas, dos ejecuciones completas</h2><p class="panel-subtitle">Serverless · duración por tarea · datos reales del Job</p></div></div><div class="table-scroll"><table class="data-table"><thead><tr><th>Semana de la foto</th><th>Foto</th><th>Ejecución</th><th>Bronce</th><th>Plata</th><th>Oro</th><th>Estado</th></tr></thead><tbody>${proof.ejecuciones.map(run=>`<tr><td>${dateLabel(run.semana_foto,true)}</td><td>${escapeHTML(run.foto)}</td><td><a href="${escapeHTML(run.url)}" target="_blank" rel="noopener">${escapeHTML(run.run_id)}</a></td><td>${duration(run.duraciones_segundos.bronze)}</td><td>${duration(run.duraciones_segundos.silver)}</td><td>${duration(run.duraciones_segundos.gold)}</td><td>${escapeHTML(run.resultado)}</td></tr>`).join("")}</tbody></table></div><div class="panel-note">${escapeHTML(proof.evidencia)} Las fotos ya estaban en Bronce; se verificó el reprocesamiento sin duplicados.</div></section>`;
}
function pipelineView() {
  const s = summary();
  if (!s)
    return `<section class="panel">${emptyState("Resumen no disponible", errorMessage(state.summary), "layers")}</section>`;
  const descriptions = {
    bronze: [
      "Bronce",
      "Conserva fotos originales, rutas, hashes y metadatos. La ingesta repetida evita duplicar archivos.",
    ],
    silver: [
      "Plata",
      "Extrae precios con OCR, aplica reglas de calidad y separa los registros rechazados.",
    ],
    gold: [
      "Oro",
      "Construye indicadores semanales, entrena el modelo y publica datos para la API.",
    ],
  };
  const quality = [
    [
      "Precisión de lo extraído",
      s.ocr.precision_sobre_extraidos,
      `${s.ocr.precios_correctos} correctos de ${s.ocr.precios_extraidos} extraídos`,
      "Mide el acierto cuando el OCR devuelve un precio.",
    ],
    [
      "Cobertura de extracción",
      s.ocr.cobertura,
      `${s.ocr.precios_extraidos} extraídos de ${s.ocr.precios_esperados} legibles`,
      "Mide cuántos precios de la referencia logra recuperar.",
    ],
    [
      "Exactitud con omisiones",
      s.ocr.exactitud_incluyendo_omisiones,
      `${s.ocr.precios_correctos} correctos de ${s.ocr.precios_esperados} legibles`,
      "Incluye como errores los precios legibles que no se extrajeron.",
    ],
  ];
  return `<div class="stats-strip">${[
    [s.datos.fotos, "fotografías procesadas"],
    [s.datos.aceptados, "precios aceptados"],
    [s.datos.rechazados, "registros rechazados"],
    [s.pipeline.ejecuciones_validadas, "ejecuciones validadas"],
  ]
    .map(
      ([value, label]) =>
        `<div class="stat"><div class="stat-value">${number(value)}</div><div class="stat-label">${label}</div></div>`,
    )
    .join("")}</div>
    <section class="panel"><div class="panel-heading"><div><h2 class="panel-title">Tres capas, una ejecución completa</h2><p class="panel-subtitle">Última validación: ${dateLabel(s.verificado_el, true)} · Estado correcto</p></div></div><div class="pipeline-details">${s.pipeline.tareas.map((task) => `<article class="pipeline-detail"><div class="pipeline-number">${icon("check")}VALIDADO</div><h3>${descriptions[task.capa][0]}</h3><p>${descriptions[task.capa][1]}</p><div class="pipeline-duration">Ejecución: ${duration(task.duracion_segundos)}</div></article>`).join("")}</div><div class="pipeline-bottom"><span>Programación: martes, 10:00 · Guatemala</span><a href="${escapeHTML(s.pipeline.url)}" target="_blank" rel="noopener">Consultar ejecución en Databricks</a></div></section>
    <div class="section-space"><h2 class="section-heading">¿Qué tan bien leemos las fotografías?</h2><p class="subtle-note quality-intro">Revisión humana de ${number(s.ocr.fotos_revisadas)} fotos con ${number(s.ocr.precios_esperados)} precios legibles. Los campos ilegibles quedan fuera de la referencia.</p><div class="quality-grid">${quality.map(([title, value, count, explanation]) => `<article class="panel quality-item"><div class="quality-title">${title}</div><div class="quality-value">${percent(value)}</div><div class="quality-explanation">${explanation}</div><div class="quality-foot">${escapeHTML(count)}</div></article>`).join("")}</div></div>
    <div class="dashboard-grid section-space"><section class="panel"><div class="panel-heading"><div><h2 class="panel-title">Reglas de calidad</h2><p class="panel-subtitle">Cada rechazo conserva su motivo y fotografía de origen</p></div></div><div class="panel-body"><ul class="rule-list">${s.reglas_calidad.map((rule) => `<li>${icon("check")}${escapeHTML(rule)}</li>`).join("")}</ul></div></section><section class="panel"><div class="panel-heading"><div><h2 class="panel-title">Evidencia del proyecto</h2><p class="panel-subtitle">Controles verificados en la última revisión</p></div></div><div class="panel-body"><ul class="rule-list"><li>${icon("check")}${number(s.datos.observaciones_mem)} observaciones MEM, separadas de las fotografías.</li><li>${icon("check")}${number(s.datos.duplicados_nueva_carga)} fotos agregadas al repetir la ingesta.</li><li>${icon(s.alertas.recepcion_confirmada ? "check" : "clock")}${s.alertas.recepcion_confirmada ? "Alerta de fallo probada y recepción del correo confirmada." : "Alerta de fallo pendiente de confirmación de recepción."}</li></ul></div></section></div>
    <div class="section-space"><h2 class="section-heading">Material para revisión</h2><div class="document-grid">${s.documentos.map((doc) => `<a class="document-link" href="/entregables/${encodeURIComponent(doc.id)}" target="_blank" rel="noopener">${icon(doc.id === "arquitectura" ? "layers" : "file")}<span><strong>${escapeHTML(doc.titulo)}</strong><small>${escapeHTML(doc.tipo)}</small></span></a>`).join("")}</div><p class="subtle-note">${escapeHTML(s.estado_documentos)}. ${escapeHTML(s.nota)}</p></div>`;
}

function endpointPath() {
  const e = state.explorer;
  const query = new URLSearchParams();
  if (
    ["/precios/actual", "/precios", "/prediccion", "/prediccion/historica", "/prediccion/historica/semanas", "/modelo/metricas"].includes(
      e.endpoint,
    ) &&
    e.source
  )
    query.set("fuente", e.source);
  if (["/prediccion", "/prediccion/historica"].includes(e.endpoint) || (e.endpoint === "/precios" && e.fuel))
    query.set("combustible", e.fuel || "super");
  if (e.endpoint === "/precios") {
    if (e.from) query.set("desde", e.from);
    if (e.until) query.set("hasta", e.until);
    query.set("limit", e.limit || "5");
    query.set("offset", e.offset || "0");
  }
  if (e.endpoint === "/prediccion") query.set("modo",e.mode || "historica");
  if ((e.endpoint === "/prediccion/historica" || (e.endpoint === "/prediccion" && e.mode !== "vigente")) && e.week) query.set("semana", e.week);
  return e.endpoint + (query.size ? "?" + query : "");
}
function apiView() {
  const e = state.explorer;
  const r = e.result;
  return `<div class="api-grid"><section class="panel"><div class="panel-heading"><div><h2 class="panel-title">Configura una consulta</h2><p class="panel-subtitle">Peticiones GET al mismo servicio del dashboard</p></div></div><div class="panel-body"><div class="endpoint-label"><span class="method">GET</span><span id="endpoint-preview">${escapeHTML(e.endpoint)}</span></div><form id="api-form"><div class="form-fields"><div class="field full"><label for="endpoint">Endpoint</label><select id="endpoint" name="endpoint">${Object.entries(
    ENDPOINTS,
  )
    .map(
      ([path, label]) =>
        `<option value="${path}"${e.endpoint === path ? " selected" : ""}>${path} · ${label}</option>`,
    )
    .join(
      "",
    )}</select></div><div class="field" data-param="fuel"><label for="api-fuel">Combustible</label><select name="fuel" id="api-fuel"><option value=""${e.fuel === "" ? " selected" : ""}>Todos</option>${Object.entries(
    FUELS,
  )
    .map(
      ([fuel, info]) =>
        `<option value="${fuel}"${e.fuel === fuel ? " selected" : ""}>${info.name}</option>`,
    )
    .join(
      "",
    )}</select></div><div class="field" data-param="source"><label for="api-source">Fuente</label><select id="api-source" name="source"><option value=""${e.source === "" ? " selected" : ""}>Predeterminada</option><option value="mem"${e.source === "mem" ? " selected" : ""}>Referencia MEM</option><option value="fotos"${e.source === "fotos" ? " selected" : ""}>Fotografías</option></select></div><div class="field" data-param="mode"><label for="api-mode">Modo de predicción</label><select id="api-mode" name="mode"><option value="historica"${e.mode === "historica" ? " selected" : ""}>Evaluación histórica</option><option value="vigente"${e.mode === "vigente" ? " selected" : ""}>Pronóstico vigente</option></select></div><div class="field" data-param="week"><label for="api-week">Semana objetivo (martes)</label><input type="date" id="api-week" name="week" value="${escapeHTML(e.week)}"></div><div class="field" data-param="history"><label for="api-from">Desde</label><input type="date" id="api-from" name="from" value="${escapeHTML(e.from)}"></div><div class="field" data-param="history"><label for="api-until">Hasta</label><input type="date" id="api-until" name="until" value="${escapeHTML(e.until)}"></div><div class="field" data-param="history"><label for="api-limit">Límite</label><input type="number" id="api-limit" name="limit" min="1" max="1000" value="${escapeHTML(e.limit)}"></div><div class="field" data-param="history"><label for="api-offset">Desplazamiento</label><input type="number" id="api-offset" name="offset" min="0" value="${escapeHTML(e.offset)}"></div></div><button type="submit" class="button button-primary request-button"${e.busy ? " disabled" : ""}>${icon(e.busy ? "refresh" : "play")}${e.busy ? "Consultando…" : "Ejecutar consulta"}</button><p class="request-hint">La respuesta es real. Un HTTP 503 puede indicar que no hay datos o predicciones vigentes; el detalle explica el motivo.</p></form></div></section><section class="panel response-panel"><div class="response-toolbar"><h2 class="panel-title">Respuesta</h2><div class="response-meta"><span id="response-status" class="http-status ${r ? (r.ok ? "good" : "bad") : ""}">${r ? (r.status ? `HTTP ${r.status}` : "Sin conexión") : "Sin ejecutar"}</span><span id="response-time">${r ? `${r.elapsed} ms` : ""}</span><button class="icon-button" id="copy-response" type="button" aria-label="Copiar respuesta JSON" title="Copiar JSON"${r ? "" : " disabled"}>${icon("copy")}</button></div></div><pre id="response-body" class="${r ? "" : "empty-response"}" tabindex="0">${r ? escapeHTML(JSON.stringify(r.data, null, 2)) : "Ejecuta una consulta para ver su respuesta JSON."}</pre><div class="curl-preview"><code id="curl-preview">${escapeHTML(`curl -i '${location.origin}${r?.path || endpointPath()}'`)}</code><button class="icon-button" id="copy-curl" type="button" title="Copiar curl" aria-label="Copiar comando curl">${icon("copy")}</button></div></section></div><section class="panel api-reference"><div class="panel-heading"><div><h2 class="panel-title">Rutas disponibles</h2><p class="panel-subtitle">También puedes explorar los parámetros y esquemas en <a href="/docs" target="_blank" rel="noopener">Swagger</a>.</p></div></div><div class="endpoint-list">${Object.entries(
    ENDPOINTS,
  )
    .map(
      ([path, label]) =>
        `<div class="endpoint-item"><span class="method">GET</span><code>${path}</code><span>${label}</span></div>`,
    )
    .join("")}</div></section>`;
}
function updateAPIFields() {
  const e = state.explorer;
  const historical = e.endpoint === "/precios";
  document.querySelectorAll('[data-param="history"]').forEach((node) => {
    node.hidden = !historical;
  });
  document.querySelectorAll('[data-param="week"]').forEach(node => {node.hidden=!(e.endpoint==="/prediccion/historica" || (e.endpoint==="/prediccion" && e.mode!=="vigente"));});
  document.querySelectorAll('[data-param="mode"]').forEach(node => {node.hidden=e.endpoint!=="/prediccion";});
  const fuel = $('[data-param="fuel"]');
  if (fuel) fuel.hidden = !(historical || ["/prediccion", "/prediccion/historica"].includes(e.endpoint));
  const source = $('[data-param="source"]');
  if (source)
    source.hidden = ![
      "/precios/actual",
      "/precios",
      "/prediccion",
      "/prediccion/historica",
      "/prediccion/historica/semanas",
      "/modelo/metricas",
    ].includes(e.endpoint);
  if ($("#endpoint-preview")) $("#endpoint-preview").textContent = e.endpoint;
}
function bindAPI() {
  const form = $("#api-form");
  if (!form) return;
  updateAPIFields();
  form.addEventListener("input", () => {
    const values = Object.fromEntries(new FormData(form));
    Object.assign(state.explorer, values);
    if (["/prediccion", "/prediccion/historica"].includes(state.explorer.endpoint) && !state.explorer.fuel) {
      state.explorer.fuel = "super";
      $("#api-fuel").value = "super";
    }
    updateAPIFields();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.explorer.busy) return;
    const path = endpointPath();
    state.explorer.busy = true;
    render();
    const result = await request(path);
    state.explorer.result = result;
    state.explorer.busy = false;
    if (state.view === "api") render();
  });
  $("#copy-response").addEventListener("click", () =>
    copyText(JSON.stringify(state.explorer.result?.data, null, 2)),
  );
  $("#copy-curl").addEventListener("click", () =>
    copyText(
      `curl -i '${location.origin}${state.explorer.result?.path || endpointPath()}'`,
    ),
  );
}
async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast("Copiado al portapapeles");
  } catch {
    toast("No se pudo copiar automáticamente. Selecciona el texto y cópialo.");
  }
}
function toast(text) {
  clearTimeout(toastTimer);
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  toastTimer = setTimeout(() => {
    $("#toast").hidden = true;
  }, 3500);
}

function paintChart() {
  const svg = $("#price-chart");
  if (!svg) return;
  const wrap = $("#chart-wrap");
  const data = historyRows().filter((row) =>
    Number.isFinite(Number(row.precio_promedio)),
  );
  if (!data.length) return;
  const width = Math.max(280, wrap.clientWidth - 30);
  const height = window.innerWidth < 470 ? 210 : 270;
  const pad = { left: 46, right: 20, top: 18, bottom: 40 };
  const dates = [...new Set(data.map((row) => isoDate(row.semana)))].sort();
  const ticks = dates.map((date) => new Date(`${date}T12:00:00Z`).getTime());
  const minX = ticks[0];
  const maxX = ticks.at(-1);
  const values = data.map((row) => Number(row.precio_promedio));
  let minY = Math.floor(Math.min(...values) - 1);
  let maxY = Math.ceil(Math.max(...values) + 1);
  if (minY === maxY) maxY++;
  const x = (date) =>
    pad.left +
    ((new Date(`${isoDate(date)}T12:00:00Z`).getTime() - minX) /
      (maxX - minX || 1)) *
      (width - pad.left - pad.right);
  const y = (price) =>
    height -
    pad.bottom -
    ((price - minY) / (maxY - minY)) * (height - pad.top - pad.bottom);
  const escape = escapeHTML;
  let markup =
    "<title>Promedio semanal por combustible en quetzales por galón</title>";
  for (let index = 0; index <= 4; index++) {
    const value = minY + ((maxY - minY) * index) / 4;
    const yy = y(value);
    markup += `<line class="chart-grid" x1="${pad.left}" y1="${yy}" x2="${width - pad.right}" y2="${yy}"/><text class="chart-axis" x="${pad.left - 11}" y="${yy + 4}" text-anchor="end">${number(value, 0)}</text>`;
  }
  const tickCount = Math.min(dates.length, width < 450 ? 3 : 5);
  const tickIndexes = new Set(
    Array.from({ length: tickCount }, (_, index) =>
      Math.round((index * (dates.length - 1)) / Math.max(1, tickCount - 1)),
    ),
  );
  tickIndexes.forEach((index) => {
    markup += `<text class="chart-axis" x="${x(dates[index])}" y="${height - 13}" text-anchor="middle">${escape(dateLabel(dates[index]))}</text>`;
  });
  Object.entries(FUELS).forEach(([fuel, info]) => {
    if (!state.selected.has(fuel)) return;
    const rows = data.filter((row) => row.combustible === fuel);
    let path = "";
    let lastDate = null;
    rows.forEach((row) => {
      const date = new Date(`${isoDate(row.semana)}T12:00:00Z`).getTime();
      const continuous = lastDate !== null && date - lastDate <= 7 * 86400000;
      path += `${continuous ? "L" : "M"}${x(row.semana).toFixed(2)},${y(Number(row.precio_promedio)).toFixed(2)} `;
      lastDate = date;
    });
    markup += `<path d="${path}" fill="none" stroke="${info.color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    rows.forEach((row, index) => {
      markup += `<circle cx="${x(row.semana)}" cy="${y(Number(row.precio_promedio))}" r="${rows.length > 25 ? 2.5 : 3.2}" fill="white" stroke="${info.color}" stroke-width="1.8" ${index === rows.length - 1 ? 'tabindex="0"' : ""}><title>${info.name}, ${escape(dateLabel(row.semana, true))}: ${money(row.precio_promedio)}</title></circle>`;
    });
  });
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.style.height = `${height}px`;
  svg.innerHTML = markup;
  const tooltip = $("#chart-tooltip");
  svg.onpointermove = (event) => {
    const rect = svg.getBoundingClientRect();
    const position = ((event.clientX - rect.left) * width) / rect.width;
    const date = dates.reduce(
      (best, item) =>
        Math.abs(x(item) - position) < Math.abs(x(best) - position)
          ? item
          : best,
      dates[0],
    );
    const rows = data.filter((row) => isoDate(row.semana) === date);
    tooltip.innerHTML = `<strong>${escape(dateLabel(date, true))}</strong>${rows.map((row) => `<div class="tooltip-row"><span>${FUELS[row.combustible]?.name || escape(row.combustible)}</span><span>${money(row.precio_promedio)}</span></div>`).join("")}`;
    tooltip.hidden = false;
    tooltip.style.left = `${Math.max(5, Math.min(wrap.clientWidth - 190, event.clientX - wrap.getBoundingClientRect().left + 12))}px`;
    tooltip.style.top = `${Math.max(110, event.clientY - wrap.getBoundingClientRect().top - 13)}px`;
  };
  svg.onpointerleave = () => {
    tooltip.hidden = true;
  };
}
function bindCharts() {
  document.querySelectorAll("[data-fuel-toggle]").forEach((button) =>
    button.addEventListener("click", () => {
      const fuel = button.dataset.fuelToggle;
      if (state.selected.has(fuel)) {
        if (state.selected.size === 1) return;
        state.selected.delete(fuel);
      } else state.selected.add(fuel);
      render();
    }),
  );
  document.querySelectorAll("[data-range]").forEach((button) =>
    button.addEventListener("click", async () => {
      const range = Number(button.dataset.range);
      if (range === state.range) return;
      state.range = range;
      button.classList.add("active");
      await loadHistory();
    }),
  );
  $("#toggle-table")?.addEventListener("click", () => {
    state.showTable = !state.showTable;
    render();
  });
  if ($("#price-chart")) {
    paintChart();
    if (typeof ResizeObserver !== "undefined") {
      let lastWidth = $("#chart-wrap").clientWidth;
      chartObserver = new ResizeObserver(() => {
        const width = $("#chart-wrap")?.clientWidth;
        if (width && width !== lastWidth) {
          lastWidth = width;
          paintChart();
        }
      });
      chartObserver.observe($("#chart-wrap"));
    }
  }
}
function render() {
  chartObserver?.disconnect();
  chartObserver = null;
  const [breadcrumb, eyebrow, title, description] = VIEWS[state.view];
  $("#breadcrumb-current").textContent = breadcrumb;
  $("#page-eyebrow").textContent = eyebrow;
  $("#page-title").textContent = title;
  $("#page-description").textContent = description;
  document.title = `${breadcrumb} · Gasolina GT`;
  document.querySelectorAll("[data-view]").forEach((link) => {
    const active = link.dataset.view === state.view;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document
    .querySelectorAll("[data-source]")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.source === state.source),
      ),
    );
  $("#source-toolbar").hidden = ["pipeline", "api"].includes(state.view);
  const service = $("#service-status");
  service.className = "service-status" + (state.health?.ok ? "" : " error");
  service.innerHTML = `<span class="status-dot"></span>${state.health?.ok ? "API conectada" : "API sin datos disponibles"}`;
  $("#cutoff-label").textContent = state.health?.ok
    ? `Corte del modelo: ${dateLabel(state.health.data.fecha_corte, true)}`
    : "Publicación no disponible";
  const notice = $("#data-notice");
  notice.hidden = true;
  if (!["pipeline", "api"].includes(state.view)) {
    if (!state.current?.ok) {
      notice.hidden = false;
      notice.className = "notice notice-error";
      notice.innerHTML =
        icon("warning") +
        `<span>${escapeHTML(errorMessage(state.current))} Puedes revisar el detalle en «Probar la API».</span>`;
    } else if (currentRows().some((row) => row.desactualizado)) {
      const latest = currentRows()
        .map((row) => isoDate(row.semana))
        .sort()
        .at(-1);
      notice.hidden = false;
      notice.className = "notice";
      notice.innerHTML =
        icon("clock") +
        `<span>Los últimos precios disponibles corresponden a la semana del <strong>${dateLabel(latest, true)}</strong>. La fecha de corte del modelo no indica una nueva observación de precios.</span>`;
    }
  }
  const renderers = {
    resumen: overview,
    historico: () => renderFuelCards() + chartPanel(true),
    predicciones: predictionsView,
    pipeline: pipelineView,
    api: apiView,
  };
  $("#view-content").innerHTML = (!["pipeline", "api"].includes(state.view) ? predictionControls() : "") + renderers[state.view]() + (state.view === "pipeline" ? orchestrationPanel() : "");
  $("#prediction-mode")?.addEventListener("change", event => {state.predictionMode=event.target.value; loadData();});
  $("#historical-week")?.addEventListener("change", event => {state.historicalWeek=event.target.value; loadData();});
  bindCharts();
  bindAPI();
}
function closeMenu() {
  const hadFocus = $("#sidebar").contains(document.activeElement);
  $("#sidebar").classList.remove("open");
  $("#sidebar").inert = window.innerWidth <= 760;
  $("#contenido").inert = false;
  $("#sidebar-overlay").hidden = true;
  $("#menu-button").setAttribute("aria-expanded", "false");
  if (hadFocus && window.innerWidth <= 760) $("#menu-button").focus();
}
window.addEventListener("hashchange", () => {
  state.view = VIEWS[location.hash.slice(1)]
    ? location.hash.slice(1)
    : "resumen";
  closeMenu();
  if (!state.loading) render();
  window.scrollTo({ top: 0, behavior: "instant" });
});
$("#menu-button").addEventListener("click", () => {
  const open = !$("#sidebar").classList.contains("open");
  $("#sidebar").classList.toggle("open", open);
  $("#sidebar").inert = !open && window.innerWidth <= 760;
  $("#contenido").inert = open && window.innerWidth <= 760;
  $("#sidebar-overlay").hidden = !open;
  $("#menu-button").setAttribute("aria-expanded", String(open));
  if (open) $("#sidebar .nav-list a").focus();
});
$("#sidebar-overlay").addEventListener("click", closeMenu);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenu();
  if (event.key === "Tab" && $("#sidebar").classList.contains("open")) {
    const targets = [...document.querySelectorAll("#sidebar a"), $("#menu-button")];
    const index = targets.indexOf(document.activeElement);
    if (event.shiftKey && index <= 0) {
      event.preventDefault(); targets.at(-1).focus();
    } else if (!event.shiftKey && index === targets.length - 1) {
      event.preventDefault(); targets[0].focus();
    }
  }
});
window.addEventListener("resize", () => {
  if (window.innerWidth > 760) closeMenu();
  else if (!$("#sidebar").classList.contains("open")) $("#sidebar").inert = true;
});
document.querySelectorAll("[data-source]").forEach((button) =>
  button.addEventListener("click", () => {
    if (button.dataset.source === state.source) return;
    state.source = button.dataset.source;
    document
      .querySelectorAll("[data-source]")
      .forEach((item) =>
        item.setAttribute(
          "aria-pressed",
          String(item.dataset.source === state.source),
        ),
      );
    loadData();
  }),
);
$("#refresh-button").addEventListener("click", loadData);
closeMenu();
loadData();

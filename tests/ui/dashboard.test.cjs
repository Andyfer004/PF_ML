// Pruebas DOM con respuestas sintéticas. No sustituyen una revisión visual.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM, VirtualConsole } = require("jsdom");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "api/ui/index.html"), "utf8");
const code = fs.readFileSync(path.join(root, "api/ui/app.js"), "utf8");
const project = JSON.parse(
  fs.readFileSync(path.join(root, "api/resources/proyecto.json")),
);
const fuels = ["super", "regular", "diesel"];
const prices = [32.49, 29.98, 41.01];
const reply = (data, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(data),
});
const historical = (price = 31.11) => ({
  datos: fuels.flatMap((fuel, index) =>
    ["2026-11-03", "2026-11-10"].map((week) => ({
      combustible: fuel,
      semana: week,
      precio_promedio: price + index,
      precio_minimo: price + index,
      precio_maximo: price + index,
      observaciones: 1,
    })),
  ),
  total: 6,
});
function backend(input) {
  const u = new URL(input, "http://dashboard.test");
  const photos = u.searchParams.get("fuente") === "fotos";
  if (u.pathname === "/health")
    return reply({
      status: "ok",
      release: "a".repeat(32),
      fecha_corte: "2026-11-23",
      origen: "S3_ORO",
    });
  if (u.pathname === "/proyecto/resumen") return reply(project);
  if (u.pathname === "/modelo/metricas")
    return reply({
      accuracy: 0.46,
      baseline_accuracy: 0.41,
      macro_f1: 0.38,
      baseline_macro_f1: 0.4,
      n_prueba: photos ? 6 : 408,
      horizonte_semanas: 2,
    });
  if (u.pathname === "/precios/actual")
    return reply({
      datos: (photos ? ["super"] : fuels).map((fuel, index) => ({
        combustible: fuel,
        precio_promedio: photos ? 38.99 : prices[index],
        semana: photos ? "2026-10-13" : "2026-11-10",
        desactualizado: true,
      })),
    });
  if (u.pathname === "/precios") return reply(historical());
  if (u.pathname === "/prediccion/historica/semanas")
    return reply({semana_predeterminada: photos ? null : "2026-11-03", datos:photos ? [] : ["2026-11-03","2026-10-27"].map(semana=>({semana,tres_combustibles:true,combustibles:fuels}))});
  if (u.pathname === "/prediccion/historica" || (u.pathname === "/prediccion" && u.searchParams.get("modo") !== "vigente"))
    return photos ? reply({detail:{mensaje:"Sin evaluación histórica"}},404) : reply({
      combustible:u.searchParams.get("combustible"),semana:u.searchParams.get("semana") || "2026-11-03",
      semana_datos:"2026-10-27",fecha_corte_simulada:"2026-11-02",entrenamiento_hasta:"2024-01-01",
      generado_el:"2026-11-24T19:00:00-06:00",horizonte_semanas:1,prediccion:"baja",probabilidad:.7,
      direccion_real:"sube",baseline:"se_mantiene",acierto:false,baseline_acierto:false,
      precio_semana_base:30,precio_semana_objetivo:31,modo:"evaluacion_historica",es_pronostico_vigente:false});
  if (u.pathname === "/prediccion")
    return photos
      ? reply(
          {
            detail: {
              codigo: "DATOS_RECIENTES_INSUFICIENTES",
              mensaje: "No hay un pronóstico vigente.",
            },
          },
          503,
        )
      : reply({
          combustible: u.searchParams.get("combustible"),
          prediccion: "baja",
          probabilidad: 0.44,
          semana: "2026-11-24",
          semana_datos: "2026-11-10",
          fecha_emision: "2026-11-23",
          horizonte_semanas: 2,
        });
  return reply({ detail: "No encontrado" }, 404);
}
async function until(
  predicate,
  message = "La interfaz no terminó de actualizarse",
) {
  for (let i = 0; i < 80; i++) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error(message);
}
function setup(handler = backend, width = 1024) {
  const errors = [];
  const console = new VirtualConsole();
  console.on("jsdomError", (error) => errors.push(error));
  const dom = new JSDOM(html, {
    url: "http://dashboard.test/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole: console,
  });
  const w = dom.window;
  Object.defineProperty(w, "innerWidth", { value: width, writable: true });
  const requests = [];
  const copied = [];
  w.fetch = async (input, options) => {
    requests.push(input);
    return handler(input, options);
  };
  w.scrollTo = () => {};
  w.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
  Object.defineProperty(w.navigator, "clipboard", {
    value: { writeText: async (text) => copied.push(text) },
  });
  w.eval(code);
  return { dom, w, d: w.document, errors, requests, copied };
}
async function ready(env) {
  await until(() => env.d.querySelectorAll(".fuel-card").length === 3);
}
async function route(env, name) {
  env.w.location.hash = name;
  await until(() =>
    env.d.querySelector(`[data-view="${name}"]`).classList.contains("active"),
  );
}
function input(env, selector, value) {
  const el = env.d.querySelector(selector);
  el.value = value;
  el.dispatchEvent(new env.w.Event("input", { bubbles: true }));
}

test("carga precios, alerta de antigüedad y gráfica desde respuestas API", async () => {
  const e = setup();
  try {
    await ready(e);
    assert.deepEqual(
      [...e.d.querySelectorAll(".amount")].map((n) => n.textContent),
      ["32.49", "29.98", "41.01"],
    );
    assert.match(
      e.d.querySelector("#data-notice").textContent,
      /últimos precios disponibles/,
    );
    assert.equal(e.d.querySelectorAll("#price-chart path").length, 3);
    assert.match(
      e.d.querySelector("#service-status").textContent,
      /API conectada/,
    );
    assert.deepEqual(e.errors, []);
  } finally {
    e.dom.window.close();
  }
});

test("cambiar a fotos elimina los precios y pronósticos de MEM", async () => {
  const e = setup();
  try {
    await ready(e);
    e.d.querySelector('[data-source="fotos"]').click();
    await until(() => e.d.querySelector(".amount").textContent === "38.99");
    assert.deepEqual(
      [...e.d.querySelectorAll(".amount")].map((n) => n.textContent),
      ["38.99", "—", "—"],
    );
    assert.equal(e.d.querySelectorAll(".fuel-footer .unavailable").length, 3);
    assert.ok(
      e.requests.some(
        (u) => u.includes("/prediccion?") && u.includes("modo=historica") && u.includes("fuente=fotos"),
      ),
    );
  } finally {
    e.dom.window.close();
  }
});

test("el explorador manda filtros, muestra HTTP 503 y copia la respuesta real", async () => {
  const e = setup();
  try {
    await ready(e);
    await route(e, "api");
    input(e, "#endpoint", "/precios");
    input(e, "#api-fuel", "diesel");
    input(e, "#api-source", "mem");
    input(e, "#api-from", "2026-10-01");
    input(e, "#api-until", "2026-11-20");
    input(e, "#api-limit", "2");
    e.d
      .querySelector("#api-form")
      .dispatchEvent(
        new e.w.Event("submit", { bubbles: true, cancelable: true }),
      );
    await until(
      () => e.d.querySelector("#response-status").textContent === "HTTP 200",
    );
    const url = new URL(e.requests.at(-1), "http://dashboard.test");
    assert.equal(url.pathname, "/precios");
    for (const [key, value] of Object.entries({
      combustible: "diesel",
      fuente: "mem",
      desde: "2026-10-01",
      hasta: "2026-11-20",
      limit: "2",
    }))
      assert.equal(url.searchParams.get(key), value);
    input(e, "#endpoint", "/prediccion");
    input(e, "#api-mode", "vigente");
    input(e, "#api-source", "fotos");
    e.d
      .querySelector("#api-form")
      .dispatchEvent(
        new e.w.Event("submit", { bubbles: true, cancelable: true }),
      );
    await until(
      () => e.d.querySelector("#response-status").textContent === "HTTP 503",
    );
    assert.match(
      e.d.querySelector("#response-body").textContent,
      /DATOS_RECIENTES_INSUFICIENTES/,
    );
    e.d.querySelector("#copy-response").click();
    await until(
      () => e.copied.length === 1 && !e.d.querySelector("#toast").hidden,
    );
    assert.equal(
      JSON.parse(e.copied[0]).detail.codigo,
      "DATOS_RECIENTES_INSUFICIENTES",
    );
    assert.deepEqual(e.errors, []);
  } finally {
    e.dom.window.close();
  }
});

test("pipeline muestra revisión humana y enlaces al material existente", async () => {
  const e = setup();
  try {
    await ready(e);
    await route(e, "pipeline");
    assert.equal(e.d.querySelectorAll(".pipeline-detail").length, 3);
    assert.equal(e.d.querySelectorAll(".quality-item").length, 3);
    assert.equal(e.d.querySelectorAll(".document-link").length, 4);
    assert.match(
      e.d.querySelector("#view-content").textContent,
      /recepción del correo confirmada/,
    );
    assert.match(
      e.d.querySelector("#view-content").textContent,
      /Documentos de entrega del equipo/,
    );
    assert.doesNotMatch(
      e.d.querySelector("#view-content").textContent,
      /@uvg.edu.gt/,
    );
  } finally {
    e.dom.window.close();
  }
});

test("errores no generan precios de ejemplo ni insertan HTML de una respuesta", async () => {
  const e = setup((u) =>
    u.startsWith("/proyecto/")
      ? backend(u)
      : reply({ detail: { mensaje: "<img src=x onerror=alert(1)>" } }, 503),
  );
  try {
    await ready(e);
    assert.equal(e.d.querySelectorAll("#data-notice img").length, 0);
    assert.match(e.d.querySelector("#data-notice").textContent, /<img/);
    assert.deepEqual(
      [...e.d.querySelectorAll(".amount")].map((n) => n.textContent),
      ["—", "—", "—"],
    );
    assert.equal(e.d.querySelector("#price-chart"), null);
    assert.ok(e.d.querySelector("#service-status").classList.contains("error"));
  } finally {
    e.dom.window.close();
  }
});

test("una respuesta antigua de MEM no sobrescribe la fuente recién seleccionada", async () => {
  let release;
  const e = setup((u) =>
    u.startsWith("/precios/actual?fuente=mem")
      ? new Promise((resolve) => {
          release = () => resolve(backend(u));
        })
      : backend(u),
  );
  try {
    await until(() => !!release);
    e.d.querySelector('[data-source="fotos"]').click();
    await ready(e);
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(e.d.querySelector(".amount").textContent, "38.99");
    assert.equal(
      e.d.querySelector('[data-source="fotos"]').getAttribute("aria-pressed"),
      "true",
    );
  } finally {
    e.dom.window.close();
  }
});

test("una respuesta de histórico anterior no pisa el último rango elegido", async () => {
  let release;
  const e = setup((input) => {
    const u = new URL(input, "http://dashboard.test");
    if (u.pathname === "/precios") {
      const weeks =
        Math.round(
          (new Date(u.searchParams.get("hasta")) -
            new Date(u.searchParams.get("desde"))) /
            (7 * 86400000),
        ) + 1;
      if (weeks === 26)
        return new Promise((resolve) => {
          release = () => resolve(reply(historical(32.22)));
        });
    }
    return backend(input);
  });
  try {
    await ready(e);
    e.d.querySelector('[data-range="26"]').click();
    await until(() => !!release);
    e.d.querySelector('[data-range="52"]').click();
    await until(
      () =>
        e.d.querySelector('[data-range="52"]').classList.contains("active") &&
        !e.d.querySelector('[data-range="26"]').classList.contains("active"),
    );
    release();
    await new Promise((resolve) => setTimeout(resolve, 20));
    const graph = e.d.querySelector("#price-chart").textContent;
    assert.match(graph, /31.11/);
    assert.doesNotMatch(graph, /32.22/);
    assert.equal(
      e.d.querySelector('[data-range="52"]').getAttribute("aria-pressed"),
      "true",
    );
  } finally {
    e.dom.window.close();
  }
});

test('la navegación móvil se abre, limita el foco y se cierra con Escape', async () => {
  const e = setup(backend, 375);
  try {
    await ready(e);
    const menu = e.d.querySelector('#menu-button');
    const sidebar = e.d.querySelector('#sidebar');
    assert.equal(sidebar.inert, true);
    menu.click();
    assert.equal(menu.getAttribute('aria-expanded'), 'true');
    assert.equal(sidebar.inert, false);
    assert.equal(e.d.querySelector('#contenido').inert, true);
    assert.equal(e.d.activeElement, e.d.querySelector('#sidebar .nav-list a'));
    e.d.dispatchEvent(new e.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.equal(menu.getAttribute('aria-expanded'), 'false');
    assert.equal(sidebar.inert, true);
    assert.equal(e.d.querySelector('#contenido').inert, false);
    assert.equal(e.d.activeElement, menu);
  } finally { e.dom.window.close(); }
});

test("evaluación histórica distingue corte, generación y resultado, y permite elegir semana", async () => {
  const e=setup();
  try {
    await ready(e);await route(e,"predicciones");
    assert.equal(e.d.querySelector("#prediction-mode").value,"historica");
    assert.match(e.d.querySelector("#view-content").textContent,/No es un pronóstico actual/);
    assert.equal(e.d.querySelectorAll(".historical-result").length,3);
    for(const label of ["Corte simulado","Resultado real","Generado realmente","Entrenamiento hasta","Línea base vs. realidad"])
      assert.match(e.d.querySelector("#view-content").textContent,new RegExp(label));
    const week=e.d.querySelector("#historical-week");week.value="2026-10-27";
    week.dispatchEvent(new e.w.Event("change",{bubbles:true}));
    await until(()=>e.requests.filter(u=>u.includes("/prediccion?")&&u.includes("modo=historica")&&u.includes("semana=2026-10-27")).length===3);
    await until(()=>!e.d.querySelector("#refresh-button").disabled);
    const mode=e.d.querySelector("#prediction-mode");mode.value="vigente";
    mode.dispatchEvent(new e.w.Event("change",{bubbles:true}));
    await until(()=>!e.d.querySelector("#refresh-button").disabled);
    assert.equal(e.d.querySelectorAll(".historical-result").length,0);
    assert.match(e.d.querySelector("#view-content").textContent,/Emisión/);
    assert.ok(e.requests.some(u=>u.startsWith("/prediccion?")&&u.includes("modo=vigente")));
    assert.deepEqual(e.errors,[]);
  } finally {e.dom.window.close();}
});

test("explorador histórico envía combustible, fuente y martes objetivo",async()=>{
  const e=setup();
  try{
    await ready(e);await route(e,"api");
    input(e,"#endpoint","/prediccion/historica");
    input(e,"#api-fuel","diesel");input(e,"#api-source","mem");input(e,"#api-week","2026-11-03");
    assert.equal(e.d.querySelector('[data-param="week"]').hidden,false);
    e.d.querySelector("#api-form").dispatchEvent(new e.w.Event("submit",{bubbles:true,cancelable:true}));
    await until(()=>e.d.querySelector("#response-status").textContent==="HTTP 200");
    const u=new URL(e.requests.at(-1),"http://dashboard.test");
    assert.equal(u.pathname,"/prediccion/historica");assert.equal(u.searchParams.get("semana"),"2026-11-03");
    assert.equal(u.searchParams.get("combustible"),"diesel");assert.equal(u.searchParams.get("fuente"),"mem");
    assert.match(e.d.querySelector("#response-body").textContent,/evaluacion_historica/);
  }finally{e.dom.window.close();}
});

test("evidencia de orquestación muestra dos semanas y duraciones reales sin llamarlas capturas",async()=>{
 const proof={computo:"serverless",evidencia:"Datos obtenidos de la API de Databricks; no son capturas del workspace.",ejecuciones:[
  {run_id:128298002079637,foto:"IMG_7665.HEIC",semana_foto:"2026-01-27",resultado:"SUCCESS",url:"https://dbc-5490c6a5-5215.cloud.databricks.com/jobs/164482682079093/runs/128298002079637",duraciones_segundos:{bronze:40,silver:70,gold:150}},
  {run_id:592769852166445,foto:"IMG_8271.HEIC",semana_foto:"2026-07-07",resultado:"SUCCESS",url:"https://dbc-5490c6a5-5215.cloud.databricks.com/jobs/164482682079093/runs/592769852166445",duraciones_segundos:{bronze:45,silver:65,gold:140}}]};
 const e=setup(u=>u.startsWith("/proyecto/resumen")?reply({...project,orquestacion:proof}):backend(u));
 try{
  await ready(e);await route(e,"pipeline");
  const panel=e.d.querySelector("#orquestacion-ejecuciones");
  assert.equal(panel.querySelectorAll("tbody tr").length,2);
  assert.match(panel.textContent,/no son capturas/);
  assert.match(panel.textContent,/IMG_7665.HEIC/);assert.match(panel.textContent,/IMG_8271.HEIC/);
  assert.equal(panel.querySelectorAll('a[target="_blank"]').length,2);
  assert.deepEqual(e.errors,[]);
 }finally{e.dom.window.close();}
});

test("endpoint requerido permite elegir modo y no envía semana histórica al pedir vigente",async()=>{
 const e=setup();
 try{
  await ready(e);await route(e,"api");
  input(e,"#endpoint","/prediccion");input(e,"#api-source","mem");input(e,"#api-week","2026-11-03");
  assert.equal(e.d.querySelector("#api-mode").value,"historica");
  assert.equal(e.d.querySelector('[data-param="week"]').hidden,false);
  e.d.querySelector("#api-form").dispatchEvent(new e.w.Event("submit",{bubbles:true,cancelable:true}));
  await until(()=>e.d.querySelector("#response-status").textContent==="HTTP 200");
  let u=new URL(e.requests.at(-1),"http://dashboard.test");
  assert.equal(u.pathname,"/prediccion");assert.equal(u.searchParams.get("modo"),"historica");assert.equal(u.searchParams.get("semana"),"2026-11-03");
  assert.match(e.d.querySelector("#response-body").textContent,/"es_pronostico_vigente": false/);
  const before=e.requests.length;
  input(e,"#api-mode","vigente");
  assert.equal(e.d.querySelector('[data-param="week"]').hidden,true);
  e.d.querySelector("#api-form").dispatchEvent(new e.w.Event("submit",{bubbles:true,cancelable:true}));
  await until(()=>e.requests.length>before && !e.d.querySelector('.request-button').disabled);
  u=new URL(e.requests.at(-1),"http://dashboard.test");
  assert.equal(u.searchParams.get("modo"),"vigente");assert.equal(u.searchParams.has("semana"),false);
  assert.deepEqual(e.errors,[]);
 }finally{e.dom.window.close();}
});

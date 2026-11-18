"use strict";

const byId = (id) => document.getElementById(id);
const clocks = {source: "Fuente", reception: "Recepción (UTC)", synthetic: "Sintético", operator: "Operador (UTC)"};
const format = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : "—";
let cursor = 0;
let records = [];
let windowSeconds = 10;
let state = {};

function timestamp(record) {
  if (record.clock === "operator" || record.clock === "reception") {
    return new Date(record.timestamp * 1000).toISOString();
  }
  return format(record.timestamp, 3) + " s";
}

function plot(id, all, end, series, range, unit) {
  const canvas = byId(id);
  const {width, height} = canvas.getBoundingClientRect();
  if (!width || !height) return;
  const dpr = window.devicePixelRatio || 1;
  const pixelWidth = Math.round(width * dpr);
  const pixelHeight = Math.round(height * dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const left = 43, right = width - 10, top = 10, bottom = height - 25;
  const start = end - windowSeconds;
  const x = (t) => left + (t - start) / windowSeconds * (right - left);
  const y = (v) => bottom - (v - range[0]) / (range[1] - range[0]) * (bottom - top);
  ctx.font = "11px system-ui";
  ctx.fillStyle = "#a2b3c8";
  ctx.textBaseline = "middle";
  ctx.strokeStyle = "#27384e";
  for (let i = 0; i <= 4; i++) {
    const yi = top + (bottom - top) * i / 4;
    const xi = left + (right - left) * i / 4;
    ctx.beginPath();
    ctx.moveTo(left, yi);
    ctx.lineTo(right, yi);
    ctx.moveTo(xi, top);
    ctx.lineTo(xi, bottom);
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.fillText(format(range[1] - (range[1] - range[0]) * i / 4, 2), left - 5, yi);
    ctx.textAlign = i === 0 ? "left" : i === 4 ? "right" : "center";
    const seconds = -windowSeconds * (1 - i / 4);
    ctx.fillText(format(seconds, Number.isInteger(seconds) ? 0 : 1) + " s", xi, bottom + 15);
  }
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, right - left, bottom - top);
  ctx.clip();
  for (let i = 0; i < all.length; i++) {
    const item = all[i];
    const at = x(item.t);
    if (item.gap) {
      const previous = x(item.gapStart);
      ctx.fillStyle = "#ff81772e";
      ctx.fillRect(previous, top, Math.max(2, at - previous), bottom - top);
    }
    if (!item.valid) {
      ctx.fillStyle = "#ffc27338";
      ctx.fillRect(at, top, 2, bottom - top);
    }
  }
  for (const [key, color] of series) {
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1.65;
    ctx.beginPath();
    let running = false;
    for (const item of all) {
      const value = item[key];
      const valid = Number.isFinite(value) && (unit === "mm" || item.valid);
      if (!valid) {
        running = false;
        continue;
      }
      if (running && !item.gap) {
        ctx.lineTo(x(item.t), y(value));
      } else {
        ctx.fillRect(x(item.t) - 1, y(value) - 1, 2, 2);
        ctx.moveTo(x(item.t), y(value));
      }
      running = true;
    }
    ctx.stroke();
  }
  ctx.restore();
}

function render() {
  const latest = records.findLast((item) => !("label" in item));
  const end = latest?.t ?? 0;
  const data = records.filter((item) => !("label" in item) && item.t >= end - windowSeconds);
  const gaps = data.filter((item) => item.gap);
  const good = data.filter((item) => item.valid).length;
  let intervals = 0, elapsed = 0;
  for (let i = 1; i < data.length; i++) {
    if (!data[i].gap || data[i].gap === "Intervalo sin muestras") {
      intervals++;
      elapsed += data[i].t - data[i - 1].t;
    }
  }
  const stale = state.offline || (state.mode === "LIVE" && !state.receiving);
  byId("rate").textContent = !stale && elapsed > 0 ? format(intervals / elapsed, 1) : "—";
  byId("valid").textContent = data.length ? format(100 * good / data.length, 1) + "%" : "—";
  byId("denominator").textContent = data.length ? good + " / " + data.length + " muestras recibidas" : "Calidad de señal · % recibido";
  byId("invalid").textContent = data.length ? data.length - good : "—";
  byId("gaps").textContent = data.length ? gaps.length : "—";
  byId("last-gap").textContent = gaps.length ? gaps.at(-1).gap + " · " + timestamp(gaps.at(-1)) : "—";
  byId("clock").textContent = latest ? clocks[latest.clock] + " · " + timestamp(latest) : "—";
  byId("pupils").textContent = !stale && latest ? format(latest.left) + " / " + format(latest.right) : "—";
  byId("gaze").textContent = !stale && latest?.valid ? format(latest.x, 3) + " / " + format(latest.y, 3) : "—";
  const values = data.flatMap(({left, right}) => [left, right]).filter(Number.isFinite);
  const min = values.length ? Math.max(0, Math.min(...values) - .15) : 2;
  const max = values.length ? Math.max(...values) + .15 : 5;
  plot("pupil-chart", data, end, [["left", "#65e5cd"], ["right", "#baadff"]], [min, max], "mm");
  plot("gaze-chart", data, end, [["x", "#65e5cd"], ["y", "#baadff"]], [0, 1], "normalized");
  const events = records.filter((item) => "label" in item && item.t >= end - windowSeconds).reverse();
  const list = byId("events");
  const signature = events.map((item) => item.seq).join(",");
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature;
  const rows = events.map((item) => {
    const li = document.createElement("li");
    const time = document.createElement("small");
    time.textContent = clocks[item.clock] + " · " + timestamp(item);
    const label = document.createElement("span");
    label.textContent = item.label;
    li.append(label, time);
    return li;
  });
  if (!rows.length) {
    const li = document.createElement("li");
    li.textContent = "Sin eventos en la ventana.";
    rows.push(li);
  }
  list.replaceChildren(...rows);
}

async function refresh() {
  try {
    const query = new URLSearchParams({after: cursor, session: state.session ?? ""});
    const response = await fetch("/api/state?" + query, {signal: AbortSignal.timeout(3000)});
    if (!response.ok) throw new Error("Respuesta del monitor");
    const session = state.session;
    state = await response.json();
    if (state.session !== session) {
      records = [];
      byId("events").dataset.signature = "";
    }
    cursor = state.cursor;
    for (const record of state.records) records.push(record);
    const latest = records.findLast((item) => !("label" in item));
    if (latest) records = records.filter((item) => item.t >= latest.t - 65);
    byId("mode").textContent = state.mode;
    byId("mode").dataset.mode = state.mode;
    byId("status").textContent = state.status;
    byId("status").dataset.receiving = state.receiving;
    byId("origin").textContent = {
      DEMO: "Señales sintéticas · simulación sin dispositivo",
      REPLAY: "Reproducción de un registro local",
      LIVE: "Tobii Pro Glasses 3 · telemetría RTSP",
    }[state.mode];
    render();
  } catch {
    state = {...state, receiving: false, offline: true};
    byId("status").textContent = "Sin conexión con el servidor del monitor";
    byId("status").dataset.receiving = false;
    render();
  }
  setTimeout(refresh, 250);
}

byId("window").addEventListener("change", (event) => {
  windowSeconds = Number(event.target.value);
  render();
});
byId("marker").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = byId("label");
  const button = event.currentTarget.querySelector("button");
  const label = input.value.trim();
  if (!label) return;
  button.disabled = true;
  const error = byId("marker-error");
  error.hidden = true;
  try {
    const response = await fetch("/api/marker", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label}),
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) throw new Error("Error al guardar el marcador");
    if (input.value.trim() === label) input.value = "";
  } catch {
    error.textContent = "No se pudo añadir el evento.";
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
});
window.addEventListener("resize", render);
refresh();

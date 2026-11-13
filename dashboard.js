"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="monitor-token"]').content;
let current = null;
function bounds(selection) {
  const end = selection === "custom" ? new Date($("to").value) : new Date();
  const start = selection === "custom" ? new Date($("from").value) : new Date(end - Number(selection) * 3600000);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start > end) throw new Error("Intervallo non valido");
  return new URLSearchParams({start: start.toISOString(), end: end.toISOString()});
}
async function post(path, value = {}) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json", "X-Monitor-Token": token}, body: JSON.stringify(value)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Richiesta non riuscita");
  return result;
}
function showError(error) { $("message").textContent = error.message; }
function row(table, cells) {
  const tr = document.createElement("tr");
  for (const cell of cells) { const td = document.createElement("td"); td.textContent = cell ?? "—"; tr.appendChild(td); }
  table.appendChild(tr);
}
function render() {
  if (!current) return;
  const selected = $("device").value;
  const rows = current.measurements.filter(r => !selected || r.device === selected);
  const latest = rows.at(-1);
  $("latest").textContent = latest ? `Ultima misura: ${latest.timestamp} | dispositivo ${latest.device || "non disponibile"} | SSID ${latest.ssid || "—"} | banda ${latest.band || "—"} | canale ${latest.channel || "—"} | collegamento ${latest.link_mbps ?? "—"} Mbps | RSSI ${latest.rssi_dbm ?? "non disponibile"} dBm` : "Nessuna misura nell'intervallo.";
  const metric = field => {
    const values = rows.map(r => r[field]), good = values.filter(v => v !== null);
    const changes = values.slice(1).map((v, i) => v !== null && values[i] !== null ? Math.abs(v - values[i]) : null).filter(v => v !== null);
    return good.length ? `latenza ${(good.reduce((a,b) => a+b, 0)/good.length).toFixed(1)} ms, perdita ${(100*(values.length-good.length)/values.length).toFixed(1)}%, jitter ${changes.length ? (changes.reduce((a,b)=>a+b,0)/changes.length).toFixed(1) : "—"} ms` : `nessuna risposta, perdita ${values.length ? "100%" : "—"}`;
  };
  $("summary").textContent = `Router: ${metric("gateway_ms")} | 1.1.1.1: ${metric("internet1_ms")} | 8.8.8.8: ${metric("internet2_ms")}`;
  const events = $("events"); events.replaceChildren();
  const category = $("category").value.toLowerCase();
  for (const e of current.events) {
    let parsed; try { parsed = JSON.parse(e.event_json); } catch { continue; }
    if (!category || String(parsed.category ?? "").toLowerCase().includes(category)) row(events, [e.imported_at, e.event_json]);
  }
  const anomalies = $("anomalies"); anomalies.replaceChildren();
  for (const a of current.anomalies) row(anomalies, [a.kind, a.started_at, a.ended_at, a.details]);
  draw(rows);
}
function draw(rows) {
  const canvas = $("chart"), ctx = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  let times; try { const params = bounds($("range").value); times = [Date.parse(params.get("start")), Date.parse(params.get("end"))]; } catch { return; }
  const x = t => Math.max(0, Math.min(w, (Date.parse(t) - times[0]) / (times[1] - times[0] || 1) * w));
  for (const [items, field, color] of [[current.events,"imported_at","#df8000"],[current.anomalies,"started_at","#8b0000"]]) {
    ctx.strokeStyle = color;
    for (const item of items) { ctx.beginPath(); ctx.moveTo(x(item[field]),0); ctx.lineTo(x(item[field]),h); ctx.stroke(); }
  }
  rows = rows.map((r, i) => {
    const window = rows.slice(Math.max(0, i - 29), i + 1);
    return {...r, loss_percent: 100 * window.filter(v => v.gateway_ms === null).length / window.length};
  });
  for (const [field, color] of [["signal_percent","#008040"],["gateway_ms","#d00000"],["internet1_ms","#005bd1"],["internet2_ms","#8000a0"],["link_mbps","#888888"],["loss_percent","#000000"]]) {
    const max = rows.reduce((m, r) => Math.max(m, r[field] ?? 0), 1); ctx.strokeStyle = color; ctx.beginPath(); let drawing = false;
    for (const r of rows) {
      if (r[field] === null) { drawing = false; continue; }
      const y = h - (r[field] / max) * (h - 5) - 2;
      if (!drawing) ctx.moveTo(x(r.timestamp),y); else ctx.lineTo(x(r.timestamp),y);
      drawing = true;
    }
    ctx.stroke();
  }
}
async function refresh() {
  const response = await fetch("/api/data?" + bounds($("range").value));
  if (!response.ok) throw new Error("Impossibile leggere i dati");
  current = await response.json();
  $("status").textContent = `Monitoraggio: ${current.running ? "attivo" : "arrestato"}${current.error ? " — " + current.error : ""} | Ultima importazione log: ${current.last_import || "mai"}`;
  if (document.activeElement !== $("latency")) $("latency").value = current.config.latency_ms;
  if (document.activeElement !== $("signal")) $("signal").value = current.config.signal_percent;
  const devices = [...new Set(current.measurements.map(r => r.device).filter(Boolean))], selected = $("device").value;
  $("device").replaceChildren(new Option("Tutti", ""), ...devices.map(d => new Option(d, d))); $("device").value = devices.includes(selected) ? selected : "";
  render();
}
$("refresh").onclick = () => refresh().catch(showError);
$("range").onchange = $("refresh").onclick;
$("device").onchange = render; $("category").oninput = render;
for (const name of ["start", "stop"]) $(name).onclick = async () => { try { await post("/api/" + name); await refresh(); } catch (e) { showError(e); } };
$("shutdown").onclick = async () => { try { await post("/api/shutdown"); clearInterval(timer); $("status").textContent = "Applicazione arrestata"; } catch(e) { showError(e); } };
$("save").onclick = async () => { try { await post("/api/config", {latency_ms: Number($("latency").value), signal_percent: Number($("signal").value)}); $("message").textContent = "Soglie salvate"; } catch(e) { showError(e); } };
$("import").onclick = async () => {
  try { const file = $("file").files[0]; if (!file || file.size > 8 * 1024 * 1024) throw new Error("Selezionare un JSON di massimo 8 MB"); const result = await post("/api/import", JSON.parse(await file.text())); $("import-status").textContent = `Eventi nuovi: ${result.added}`; await refresh(); } catch(e) { showError(e); }
};
$("export").onclick = () => { try { location.href = "/api/export?" + bounds($("export-range").value); } catch(e) { showError(e); } };
refresh().catch(showError);
const timer = setInterval(() => refresh().catch(showError), 10000);

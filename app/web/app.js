// Workspace: library (samples / upload), drawing viewer with board summary, and the assistant chat.

const $ = id => document.getElementById(id);
const ROUTES = { compute: ["📏", "Measured from drawing"], spec: ["📘", "From the specification"], visual: ["👁️", "Read from the image"],
                 compliance: ["⚖️", "Compliance check"], error: ["⚠️", "Error"] };

const state = {
  config: { desktop: false, default_mode: "online" },
  categories: [],
  src: "samples",
  cat: "db",
  drawing: null,        // current drawing id (sample name or upload id)
  spec: null,           // uploaded spec id; samples use their own spec on the server
  page: 1,              // current page of a PDF drawing
  catsOpen: false,      // drawing-type chooser stays hidden until "Samples" is clicked
  sampleDrawing: null,  // what the Samples tab had open, restored when switching back
  upload: { drawing: null, spec: null, specName: null },
  info: null,           // /api/drawing response
  mode: "online",
  fallback: false,      // online was wanted but the model could not start
  histories: {},        // chat per drawing + spec + mode
  busy: false,
};

const chatKey = () => `${state.drawing}|${state.spec}|${state.mode}`;
const turnsFor = () => (state.histories[chatKey()] ??= []);

// ------------------------------------------------------------------ tiny markdown (answers are short)
function inline(s) {
  return s.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|\W)\*([^*]+)\*(?=\W|$)/g, "$1<i>$2</i>");
}
function markdown(text) {
  const lines = esc(text).split("\n");
  let out = "", list = null, para = [], table = [];
  const flushPara = () => { if (para.length) { out += `<p>${inline(para.join("<br>"))}</p>`; para = []; } };
  const flushList = () => { if (list) { out += `</${list}>`; list = null; } };
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter(r => !/^\|?\s*:?-{2,}/.test(r)).map(r => r.replace(/^\||\|$/g, "").split("|").map(c => inline(c.trim())));
    out += "<table>" + rows.map((r, i) => `<tr>${r.map(c => i ? `<td>${c}</td>` : `<th>${c}</th>`).join("")}</tr>`).join("") + "</table>";
    table = [];
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (/^\s*\|.*\|\s*$/.test(line)) { flushPara(); flushList(); table.push(line.trim()); continue; }
    flushTable();
    const ul = line.match(/^\s*[-*•]\s+(.*)/), ol = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (ul || ol) {
      flushPara();
      const kind = ul ? "ul" : "ol";
      if (list !== kind) { flushList(); out += `<${kind}>`; list = kind; }
      out += `<li>${inline((ul || ol)[1])}</li>`;
    } else if (!line.trim()) { flushPara(); flushList(); }
    else { flushList(); para.push(line.replace(/^#{1,6}\s+/, "")); }
  }
  flushPara(); flushList(); flushTable();
  return out;
}

// ------------------------------------------------------------------ status
function renderStatus() {
  const pill = $("status");
  if (state.mode === "offline") pill.innerHTML = '<span class="dot off"></span>Offline <span class="sub">· runs on this computer</span>';
  else if (state.fallback) pill.innerHTML = '<span class="dot err"></span>Online AI unavailable <span class="sub">· using built-in rules</span>';
  else pill.innerHTML = '<span class="dot"></span>Online';
  document.querySelectorAll("#modeSwitch button").forEach(b => b.classList.toggle("on", b.dataset.mode === state.mode));
}

// ------------------------------------------------------------------ library
function renderLibrary() {
  document.querySelectorAll("#srcSwitch button").forEach(b => b.classList.toggle("on", b.dataset.src === state.src));
  const samples = state.src === "samples";
  $("cats").hidden = !samples || !state.catsOpen;
  $("sampleRow").hidden = !samples;
  $("uploads").hidden = samples;
  if (!samples) return;

  $("cats").innerHTML = state.categories.map(c => `
    <button class="cat t-${c.id}${c.id === state.cat ? " on" : ""}" data-cat="${c.id}">
      ${c.icon} ${esc(c.label)} <span class="count">· ${c.samples.length}</span><span class="badge">${c.badge}</span>
    </button>`).join("");

  const cat = state.categories.find(c => c.id === state.cat);
  if (!cat) return;
  $("tileLabel").textContent = `${cat.samples.length} ${cat.label.toLowerCase()}${cat.samples.length > 7 ? " · scroll for more →" : ""}`;
  $("tiles").innerHTML = cat.samples.map((s, i) => `
    <button class="tile${s.id === state.drawing ? " on" : ""}" data-id="${s.id}" style="animation-delay:${i * 0.03}s">
      <img src="/api/image/${s.id}?size=thumb" alt="${esc(s.title)}" loading="lazy"><span>${esc(s.short)}</span>
    </button>`).join("");
  const current = cat.samples.find(s => s.id === state.drawing) || cat.samples[0];
  $("specBadge").innerHTML = current?.spec ? `<span class="spec-badge">📘 ${esc(current.spec)}</span>`
                                           : '<span class="spec-badge none">No specification for this type</span>';
  $("tiles").querySelector(".tile.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function selectCategory(id) {
  state.cat = id;
  const cat = state.categories.find(c => c.id === id);
  if (!cat.samples.some(s => s.id === state.drawing)) openDrawing(cat.samples[0]?.id);
  renderLibrary();
}

// ------------------------------------------------------------------ viewer
function boardHtml(rows) {
  const loads = rows.map(r => Number(r.total_LOAD_W) || 0);
  const peak = Math.max(...loads, 1);
  const total = loads.reduce((a, b) => a + b, 0);
  const rcds = rows.filter(r => r.rcd).length;
  const body = rows.map((r, i) => {
    const feeds = Object.entries(r.feeds || {}).filter(([k]) => k !== "CABLE" && k !== "RCD").map(([k, n]) => `${n} ${k.toLowerCase().replace("_", " ")}`).join(", ");
    return `<div class="crow" style="--d:${(i * 0.07).toFixed(2)}s" title="${esc(feeds)}">
      <span class="ctag">${esc(r.tag)}</span><span class="crat">${esc(r.RATING_A ?? "?")}A ${esc(r.CURVE ?? "")}</span>
      <span class="cbar"><i style="--w:${(loads[i] / peak * 100).toFixed(0)}%"></i></span>
      <span class="cload">${loads[i].toLocaleString()} W</span>
      ${r.rcd ? '<span class="rcd on">🛡 RCD</span>' : '<span class="rcd">no RCD</span>'}</div>`;
  }).join("");
  return `<div class="board"><div class="board-h"><span class="t">⚡ Board at a glance</span>
    <span class="k"><span><b>${rows.length}</b> circuits</span><span><b>${(total / 1000).toFixed(1)}</b> kW</span><span><b>${rcds}</b> RCD</span></span></div>${body}</div>`;
}

function renderViewer() {
  const d = state.info;
  if (!d) {
    $("viewer").innerHTML = state.src === "upload"
      ? '<div class="empty"><div class="ico">⬆️</div><h4>Upload your drawing</h4><p>Drop a DXF or PDF drawing in the box above. Add a spec PDF for compliance checks.</p></div>'
      : '<div class="empty"><div class="ico">📐</div><h4>No drawing open</h4><p>Pick a sample from the library or upload a drawing.</p></div>';
    return;
  }
  const specTitle = d.spec?.title || (state.src === "upload" ? state.upload.specName : null);
  if (d.kind === "pdf") {
    const pages = d.pages > 1
      ? `<div class="pages">${Array.from({ length: d.pages }, (_, i) => `<button class="${i + 1 === state.page ? "on" : ""}" data-page="${i + 1}">${i + 1}</button>`).join("")}</div>` : "";
    $("viewer").innerHTML = `
      <div class="vbar"><div><div class="t">${esc(d.title)}</div><div class="s">PDF drawing${specTitle ? ` · 📘 ${esc(specTitle)}` : ""}</div></div>
        <div class="vchips"><span><b>${d.pages}</b>page${d.pages > 1 ? "s" : ""}</span><span><b>${d.scanned ? "scanned" : "vector"}</b>PDF</span><span><b>AI</b>reads it</span></div></div>
      ${pages}
      <div class="canvas pdf skeleton"><img alt="${esc(d.title)}" src="${d.image}?page=${state.page}"
           onload="this.classList.add('ready'); this.parentElement.classList.remove('skeleton')"></div>
      <div class="note">🤖 Answers are read from the page image by the online AI, so values come from the labels on the drawing.
        For measured answers, upload the DXF version.</div>`;
    return;
  }
  const domain = d.domain ? d.domain[0].toUpperCase() + d.domain.slice(1) : "";
  const nLayers = Array.isArray(d.layers) ? d.layers.length : Object.keys(d.layers || {}).length;
  $("viewer").innerHTML = `
    <div class="vbar"><div><div class="t">${esc(d.title)}</div><div class="s">${esc(domain)}${specTitle ? ` · 📘 ${esc(specTitle)}` : ""}</div></div>
      <div class="vchips"><span><b>${d.entities}</b>entities</span><span><b>${nLayers}</b>layers</span><span><b>${esc(d.units)}</b>units</span></div></div>
    <div class="canvas skeleton"><img alt="${esc(d.title)}" src="${d.image}"
         onload="this.classList.add('ready'); this.parentElement.classList.remove('skeleton')"></div>
    ${d.board.length ? boardHtml(d.board) : ""}
    ${(d.warnings || []).map(w => `<div class="warn">⚠️ ${esc(w)}</div>`).join("")}
    <details><summary>Layers and annotations</summary><pre>${esc(JSON.stringify({ layers: d.layers, text: d.text }, null, 1))}</pre></details>`;
}

async function openDrawing(id) {
  if (!id) { state.drawing = null; state.info = null; renderViewer(); renderChat(); return; }
  state.drawing = id;
  state.page = 1;
  const url = new URL(location);
  if (id.startsWith("up-")) url.searchParams.delete("sample"); else url.searchParams.set("sample", id);
  window.history.replaceState(null, "", url);
  $("viewer").innerHTML = '<div class="canvas skeleton"></div>';
  try {
    const info = await api(`/api/drawing/${encodeURIComponent(id)}`);
    if (state.drawing !== id) return;  // a newer click won
    state.info = info;
  } catch (e) { toast(`Could not open the drawing: ${e.message}`, true); state.info = null; }
  renderViewer();
  renderChat();
  document.querySelectorAll(".tile").forEach(t => t.classList.toggle("on", t.dataset.id === id));
}

// ------------------------------------------------------------------ chat
function answerHtml(a) {
  const [icon, label] = ROUTES[a.route] || ["•", a.route];
  let head = `<span class="route${a.route === "error" ? " error" : ""}">${icon} ${esc(label)}</span>`;
  if (a.route === "compliance" && (a.final === "PASS" || a.final === "FAIL")) {
    head += `<span class="stamp ${a.final.toLowerCase()}">${a.final === "PASS" ? "✓ Complies" : "✕ Does not comply"}</span>`;
  }
  const body = markdown((a.text || "").split("\n").filter(l => !l.startsWith("FINAL:")).join("\n"));
  const final = a.final && a.route !== "compliance" ? `<span class="final"><b>FINAL</b>${esc(a.final)}</span>` : "";
  let how = "";
  if ((a.trace || []).length || (a.sources || []).length) {
    how = `<details><summary>🔎 How this was answered · ${a.trace.length} tool calls · ${a.sources.length} sources</summary>
      ${a.trace.map(s => `<div><b>${esc(s.tool)}</b> <code>${esc(JSON.stringify(s.args))}</code></div>
        <pre>${esc(JSON.stringify(s.result, null, 1).slice(0, 1500))}</pre>`).join("")}
      ${a.sources.map(s => `<div class="clause"><div class="pg">Page ${esc(s.page)}</div>${esc(s.text)}</div>`).join("")}</details>`;
  }
  return `${head}<div>${body}</div>${final}${how}<div class="meta">⏱ ${a.latency_s} s</div>`;
}

function msgHtml(role, inner) {
  return `<div class="msg ${role}"><div class="av">${role === "user" ? "🧑‍💻" : "📐"}</div><div class="bubble">${inner}</div></div>`;
}

function renderChat() {
  const turns = turnsFor();
  const box = $("messages");
  if (!turns.length) {
    const what = state.info ? `about <b>${esc(state.info.title)}</b>` : "once a drawing is open";
    box.innerHTML = `<div class="empty"><div class="ico">💬</div><h4>Ask anything</h4><p>Ask ${what}, or tap a suggestion below.</p></div>`;
  } else {
    box.innerHTML = turns.map(t => msgHtml("user", esc(t.question)) + msgHtml("bot", answerHtml(t))).join("");
    box.scrollTop = box.scrollHeight;
  }
  $("answerCount").textContent = turns.length ? `· ${turns.length} answer${turns.length > 1 ? "s" : ""}` : "";
  $("clearBtn").hidden = !turns.length;
  $("suggest").innerHTML = (state.info?.examples || []).map(q => `<button type="button">${esc(q)}</button>`).join("");
}

async function ask(question) {
  question = question.trim();
  if (!question || state.busy) return;
  state.busy = true;
  $("send").disabled = true;
  const turns = turnsFor();
  const box = $("messages");
  if (!turns.length) box.innerHTML = "";
  box.insertAdjacentHTML("beforeend", msgHtml("user", esc(question)) +
    msgHtml("bot", '<div class="thinking" id="thinking"><span class="bars"><i></i><i></i><i></i><i></i></span>Measuring the drawing and reading the spec…</div>'));
  box.scrollTop = box.scrollHeight;
  let answer;
  try {
    answer = await api("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, drawing: state.drawing, spec: state.spec, mode: state.mode, page: state.page }) });
  } catch (e) {
    answer = { question, route: "error", text: `Something failed: ${e.message}`, final: null, trace: [], sources: [], latency_s: 0 };
  }
  if (answer.fallback !== state.fallback) { state.fallback = !!answer.fallback; renderStatus(); }
  turns.push(answer);
  state.busy = false;
  $("send").disabled = false;
  renderChat();
}

// ------------------------------------------------------------------ uploads
const DROP_LABEL = { drawing: "Drawing · DXF or PDF", spec: "Specification PDF" };

async function uploadFile(file, slot) {
  // A PDF dropped in the spec box while no drawing is uploaded is almost always the drawing itself.
  if (slot === "spec" && !state.upload.drawing) {
    slot = "drawing";
    toast(`No drawing uploaded yet, so ${file.name} is opened as the drawing. Drop a spec PDF in the second box for compliance checks.`);
  }
  const drop = slot === "drawing" ? $("dropDxf") : $("dropPdf");
  const label = drop.querySelector("b");
  label.textContent = slot === "spec" ? `Reading ${file.name}… (scanned pages take a little longer)` : `Uploading ${file.name}…`;
  const form = new FormData();
  form.append("file", file);
  form.append("mode", state.mode);
  form.append("role", slot);
  try {
    const res = await api("/api/upload", { method: "POST", body: form });
    drop.classList.add("done");
    label.textContent = `✓ ${file.name}`;
    // Whatever was on screen before (a sample or an earlier upload), the uploaded file now takes over.
    if (state.src !== "upload") { state.sampleDrawing = state.drawing; state.src = "upload"; renderLibrary(); }
    if (slot === "drawing") {
      state.upload.drawing = res.id;
      state.spec = state.upload.spec;                 // never the sample's spec
      state.info = null;
      await openDrawing(res.id);
      if (state.info?.id !== res.id) throw new Error(`${file.name} was uploaded but could not be opened`);
      toast(`Now showing and answering from ${file.name}`);
    } else {
      state.upload.spec = state.spec = res.id;
      state.upload.specName = file.name;
      renderViewer(); renderChat();
      toast("Specification ready for compliance questions");
    }
  } catch (e) {
    drop.classList.remove("done");
    label.textContent = DROP_LABEL[slot];
    toast(e.message, true);
  }
}

function bindDrop(drop, kind) {
  const input = drop.querySelector("input");
  input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0], kind));
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, () => drop.classList.remove("drag")));
  drop.addEventListener("drop", e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) uploadFile(f, kind); });
}

// ------------------------------------------------------------------ wiring
function bind() {
  bindThemeToggle();
  $("wave").innerHTML = waveSvg();
  $("srcSwitch").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.src === "samples") {
      const already = state.src === "samples";
      state.catsOpen = already ? !state.catsOpen : true;   // clicking Samples again collapses the chooser
      if (already) { renderLibrary(); return; }
    }
    if (b.dataset.src === state.src) return;
    state.src = b.dataset.src;
    if (state.src === "upload") {
      state.sampleDrawing = state.drawing;
      state.spec = state.upload.spec;
      renderLibrary();
      openDrawing(state.upload.drawing);          // empty until something is uploaded
    } else {
      state.spec = null;                          // samples use their own spec
      renderLibrary();
      openDrawing(state.sampleDrawing || state.categories.find(c => c.id === state.cat)?.samples[0]?.id);
    }
  });
  $("cats").addEventListener("click", e => { const b = e.target.closest(".cat"); if (b) selectCategory(b.dataset.cat); });
  $("tiles").addEventListener("click", e => {
    const t = e.target.closest(".tile"); if (!t || t.dataset.id === state.drawing) return;
    openDrawing(t.dataset.id);
    const cat = state.categories.find(c => c.id === state.cat);
    const s = cat?.samples.find(x => x.id === t.dataset.id);
    $("specBadge").innerHTML = s?.spec ? `<span class="spec-badge">📘 ${esc(s.spec)}</span>` : '<span class="spec-badge none">No specification for this type</span>';
  });
  $("modeSwitch").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    state.mode = b.dataset.mode; state.fallback = false; renderStatus(); renderChat();
  });
  $("suggest").addEventListener("click", e => { const b = e.target.closest("button"); if (b) ask(b.textContent); });
  $("clearBtn").addEventListener("click", () => { state.histories[chatKey()] = []; renderChat(); });
  const q = $("question");
  $("composer").addEventListener("submit", e => { e.preventDefault(); ask(q.value); q.value = ""; q.style.height = ""; });
  q.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); } });
  q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = `${Math.min(q.scrollHeight, 140)}px`; });
  bindDrop($("dropDxf"), "drawing");
  bindDrop($("dropPdf"), "spec");
  $("viewer").addEventListener("click", e => {
    const b = e.target.closest(".pages button"); if (!b) return;
    state.page = Number(b.dataset.page); renderViewer();
  });
}

async function init() {
  bind();
  try {
    const [cfg, cat] = await Promise.all([api("/api/config"), api("/api/samples")]);
    state.config = cfg;
    state.categories = cat.categories;
  } catch (e) { toast(`Could not reach the server: ${e.message}`, true); return; }
  state.mode = state.config.default_mode;
  $("modeSwitch").hidden = !state.config.desktop;   // offline mode only in the installed desktop copy
  renderStatus();

  const wanted = new URLSearchParams(location.search).get("sample");
  const owner = state.categories.find(c => c.samples.some(s => s.id === wanted));
  state.cat = owner ? owner.id : "db";
  renderLibrary();
  await openDrawing(owner ? wanted : state.categories.find(c => c.id === state.cat)?.samples[0]?.id);
  renderLibrary();
}

init();

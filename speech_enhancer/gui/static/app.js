import WaveSurfer from "https://unpkg.com/wavesurfer.js@7.12.12/dist/wavesurfer.esm.js";
import RegionsPlugin from "https://unpkg.com/wavesurfer.js@7.12.12/dist/plugins/regions.esm.js";
import TimelinePlugin from "https://unpkg.com/wavesurfer.js@7.12.12/dist/plugins/timeline.esm.js";

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const api = async (method, url, body) => {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${url}: ${res.status}`);
  return res.json();
};

const fmt = (s, decimals = 1) => {
  if (s == null || isNaN(s)) return "–";
  const m = Math.floor(s / 60);
  const sec = (s - m * 60).toFixed(decimals).padStart(decimals ? 3 + decimals : 2, "0");
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
};
const STATUS = {
  new: "new", queued: "queued", analyzing: "analysing", ready: "ready",
  enhancing: "enhancing", done: "done", error: "error",
};

// ------------------------------------------------------------------------------------
// state
// ------------------------------------------------------------------------------------
const S = {
  files: [],
  selected: null, // file id
  detail: null, // details of selected file
  detailVersion: -1,
  wsOrig: null,
  wsEnh: null,
  regions: null,
  enhKey: null,
  source: "original", // A/B
  selectedSeg: null,
  selectedCut: null,
  selectedSpeech: null,
  undo: [], // {cuts, speech} snapshots for Cmd+Z
  drawing: false,
  previewAudio: null,
  settings: null,
};

// ------------------------------------------------------------------------------------
// polling
// ------------------------------------------------------------------------------------
async function poll() {
  try {
    const st = await api("GET", "/api/state");
    S.files = st.files;
    S.settings = st.settings;
    $("modelStatus").textContent = `Model: ${st.model}${st.queue ? ` · ${st.queue} queued job(s)` : ""}`;
    renderSidebar();
    if (!S.selected && S.files.length) select(S.files[0].id);
    const cur = S.files.find((f) => f.id === S.selected);
    if (cur) {
      renderStatus(cur);
      if (cur.version !== S.detailVersion) await loadDetail();
    }
  } catch (e) {
    $("modelStatus").textContent = "Server unreachable";
  }
}
setInterval(poll, 700);
poll();

// ------------------------------------------------------------------------------------
// sidebar
// ------------------------------------------------------------------------------------
function renderSidebar() {
  $("sidebarEmpty").classList.toggle("hidden", S.files.length > 0);
  const ul = $("fileList");
  ul.innerHTML = "";
  for (const f of S.files) {
    const li = document.createElement("li");
    li.className = "file-item" + (f.id === S.selected ? " selected" : "");
    const chipClass = f.output_stale && f.status === "done" ? "stale" : f.status;
    const chipText = f.output_stale && f.status === "done" ? "outdated" : STATUS[f.status] || f.status;
    const busy = ["analyzing", "enhancing"].includes(f.status);
    li.innerHTML = `
      <span class="name" title="${f.path}">${f.name}</span>
      <span class="chip ${chipClass}">${chipText}</span>
      <span class="sub"><span>${f.duration ? fmt(f.duration, 0) : "…"}</span>
        <span>${f.segments ? f.segments + " segments" : ""}</span></span>
      ${busy ? `<div class="mini"><div style="width:${(f.progress * 100).toFixed(1)}%"></div></div>` : ""}`;
    li.onclick = () => select(f.id);
    ul.appendChild(li);
  }
}

function select(fid) {
  if (S.selected === fid) return;
  S.selected = fid;
  S.detail = null;
  S.detailVersion = -1;
  S.selectedSeg = S.selectedCut = S.selectedSpeech = null;
  S.undo = [];
  S.enhKey = null;
  destroyWaves();
  renderSidebar();
  poll();
}

// ------------------------------------------------------------------------------------
// detail
// ------------------------------------------------------------------------------------
async function loadDetail() {
  const fid = S.selected;
  const d = await api("GET", `/api/files/${fid}`);
  if (fid !== S.selected) return;
  const first = !S.detail || S.detail.id !== d.id;
  S.detail = d;
  S.detailVersion = d.version;
  $("emptyState").classList.add("hidden");
  $("detail").classList.remove("hidden");
  $("fileName").textContent = d.name;
  const seg = d.segmentation;
  $("fileMeta").textContent = [
    d.duration ? fmt(d.duration, 1) : null,
    d.source_sr ? `${(d.source_sr / 1000).toFixed(1)} kHz` : null,
    d.channels ? (d.channels === 1 ? "mono" : `${d.channels} channels`) : null,
    seg ? `speech ${(seg.speech_fraction * 100).toFixed(0)}%` : null,
    d.rtf ? `last run ${(1 / d.rtf).toFixed(1)}× real time` : null,
  ].filter(Boolean).join(" · ");
  renderStatus(d);

  if (seg && (first || !S.wsOrig)) await buildOriginal();
  if (seg) {
    drawRegions();
    renderSegments();
    drawVad();
  }
  const enhKey = d.output_path ? `${d.output_path}:${d.output_mtime}` : null;
  if (enhKey !== S.enhKey) await buildEnhanced(enhKey);
  $("staleBadge").classList.toggle("hidden", !d.output_stale);
}

function renderStatus(f) {
  const busy = ["analyzing", "enhancing", "queued"].includes(f.status);
  $("progressBar").style.width = `${((f.progress || 0) * 100).toFixed(1)}%`;
  const eta = f.eta_s != null ? ` · ${fmt(f.eta_s, 0)} left` : "";
  $("statusText").textContent = `${f.message || STATUS[f.status] || f.status}${f.status === "enhancing" ? eta : ""}`;
  $("progressBar").parentElement.classList.toggle("hidden", !busy);
  const enh = $("enhanceBtn");
  if (f.status === "enhancing" || f.status === "queued") {
    enh.textContent = "■ Cancel";
    enh.classList.remove("primary");
    enh.disabled = false;
  } else {
    enh.textContent = f.has_output ? "✦ Re-enhance" : "✦ Enhance";
    enh.classList.add("primary");
    enh.disabled = !["ready", "done", "error"].includes(f.status) || !f.segments;
  }
  $("resegmentBtn").disabled = busy || !f.segments;
}

// ------------------------------------------------------------------------------------
// waveforms
// ------------------------------------------------------------------------------------
function destroyWaves() {
  S.wsOrig?.destroy();
  S.wsEnh?.destroy();
  S.wsOrig = S.wsEnh = S.regions = null;
  S.source = "original";
  updateAB();
}

const zoomPx = () => Number($("zoom").value);

async function buildOriginal() {
  const fid = S.selected;
  const peaks = await api("GET", `/api/files/${fid}/peaks/original`);
  if (fid !== S.selected) return;
  S.wsOrig?.destroy();
  S.regions = RegionsPlugin.create();
  S.wsOrig = WaveSurfer.create({
    container: $("waveOriginal"),
    height: 130,
    waveColor: css("--wave"),
    progressColor: css("--wave-progress"),
    cursorColor: css("--text"),
    barWidth: 2, barGap: 1, barRadius: 2,
    url: `/api/files/${fid}/audio/original`,
    peaks: [peaks],
    duration: S.detail.duration,
    minPxPerSec: zoomPx(),
    autoCenter: true,
    plugins: [S.regions, TimelinePlugin.create({ container: $("timeline"), style: { color: css("--muted") } })],
  });
  const ws = S.wsOrig;
  // Regions are positioned relative to the media duration: draw them once it is known.
  ws.on("ready", () => { drawRegions(); drawVad(); });
  ws.on("timeupdate", (t) => { if (S.source === "original") updateTime(t); });
  ws.on("interaction", (t) => { syncTime(t); selectSegAt(t); });
  ws.on("play", () => ($("playBtn").textContent = "❚❚"));
  ws.on("pause", () => ($("playBtn").textContent = "▶"));
  ws.on("scroll", (start, end, left) => { S.wsEnh?.setScroll(left); drawVad(start, end); });
  ws.on("zoom", () => drawVad());
  ws.on("redraw", () => drawVad());
  ws.on("dblclick", (relX) => addCut(relX * S.detail.duration));
  // Drag on an empty part of the waveform draws a new speech region.
  S.regions.enableDragSelection({ color: css("--speech-sel") });
  S.regions.on("region-created", (r) => {
    if (S.drawing || r.id.startsWith("cut-") || r.id.startsWith("speech-") || r.id === "selected") return;
    commitSpeechFromRegions();
  });
  S.regions.on("region-updated", (r) => {
    if (r.id.startsWith("cut-")) commitCutsFromRegions();
    else if (r.id !== "selected") commitSpeechFromRegions();
  });
  S.regions.on("region-clicked", (r, e) => {
    e.stopPropagation();
    if (r.id.startsWith("cut-")) {
      if (e.altKey) removeCut(Number(r.id.slice(4)));
      else { S.selectedCut = Number(r.id.slice(4)); S.selectedSpeech = null; drawRegions(); }
    } else if (r.id.startsWith("speech-")) {
      const i = Number(r.id.slice(7));
      if (e.altKey) { removeSpeech(i); return; }
      S.selectedSpeech = i;
      S.selectedCut = null;
      const t = timeAtClient(e.clientX);
      syncTime(t);
      selectSegAt(t);
      drawRegions();
    }
  });
}

async function buildEnhanced(key) {
  S.enhKey = key;
  S.wsEnh?.destroy();
  S.wsEnh = null;
  const d = S.detail;
  $("enhancedEmpty").classList.toggle("hidden", !!key);
  if (!key) { if (S.source === "enhanced") S.source = "original"; updateAB(); return; }
  const peaks = await api("GET", `/api/files/${d.id}/peaks/enhanced`);
  S.wsEnh = WaveSurfer.create({
    container: $("waveEnhanced"),
    height: 110,
    waveColor: css("--wave-enh"),
    progressColor: css("--wave-enh-progress"),
    cursorColor: css("--text"),
    barWidth: 2, barGap: 1, barRadius: 2,
    url: `/api/files/${d.id}/audio/enhanced?v=${encodeURIComponent(d.output_mtime)}`,
    peaks: [peaks],
    duration: d.duration,
    minPxPerSec: zoomPx(),
    autoCenter: true,
    hideScrollbar: true,
  });
  S.wsEnh.on("timeupdate", (t) => { if (S.source === "enhanced") updateTime(t); });
  S.wsEnh.on("interaction", (t) => { syncTime(t); selectSegAt(t); });
  S.wsEnh.on("play", () => ($("playBtn").textContent = "❚❚"));
  S.wsEnh.on("pause", () => ($("playBtn").textContent = "▶"));
  updateAB();
}

function updateTime(t) { $("timeLabel").textContent = fmt(t, 1); }

function syncTime(t) {
  for (const ws of [S.wsOrig, S.wsEnh]) if (ws && Math.abs(ws.getCurrentTime() - t) > 0.01) ws.setTime(t);
  updateTime(t);
}

const active = () => (S.source === "enhanced" && S.wsEnh ? S.wsEnh : S.wsOrig);

function togglePlay() {
  stopPreview();
  active()?.playPause();
}

function switchSource(src) {
  if (src === S.source || (src === "enhanced" && !S.wsEnh)) return;
  const from = active();
  const playing = from?.isPlaying();
  const t = from?.getCurrentTime() || 0;
  from?.pause();
  S.source = src;
  const to = active();
  to.setTime(t);
  if (playing) to.play();
  updateAB();
}

function updateAB() {
  document.querySelectorAll(".ab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.src === S.source);
    if (b.dataset.src === "enhanced") b.disabled = !S.wsEnh;
  });
}
document.querySelectorAll(".ab-btn").forEach((b) => (b.onclick = () => switchSource(b.dataset.src)));

$("zoom").oninput = () => {
  for (const ws of [S.wsOrig, S.wsEnh]) ws?.zoom(zoomPx());
};

// ------------------------------------------------------------------------------------
// VAD probability strip (drawn for the visible time window)
// ------------------------------------------------------------------------------------
function drawVad(start, end) {
  const cv = $("vadCanvas");
  const d = S.detail;
  if (!d?.vad || !S.wsOrig) return;
  const w = (cv.width = cv.clientWidth * devicePixelRatio);
  const h = (cv.height = 28 * devicePixelRatio);
  const ctx = cv.getContext("2d");
  if (start == null) {
    const wrapper = S.wsOrig.getWrapper();
    const total = wrapper.scrollWidth || 1;
    const scroll = S.wsOrig.getScroll();
    start = (scroll / total) * d.duration;
    end = ((scroll + wrapper.parentElement.clientWidth) / total) * d.duration;
  }
  const { probs, hop_s } = d.vad;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = css("--speech");
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = css("--ok");
  ctx.lineWidth = 1.5 * devicePixelRatio;
  ctx.beginPath();
  for (let x = 0; x < w; x++) {
    const t = start + ((end - start) * x) / w;
    const p = probs[Math.min(probs.length - 1, Math.max(0, Math.floor(t / hop_s)))] || 0;
    const y = h - p * (h - 2) - 1;
    x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke();
  ctx.fillStyle = css("--cut");
  for (const c of d.segmentation.cuts) {
    if (c < start || c > end) continue;
    ctx.fillRect(((c - start) / (end - start)) * w - devicePixelRatio, 0, 2 * devicePixelRatio, h);
  }
}
window.addEventListener("resize", () => drawVad());

// ------------------------------------------------------------------------------------
// regions: speech areas, cut markers, selected segment
// ------------------------------------------------------------------------------------
function drawRegions() {
  if (!S.regions || !S.detail?.segmentation || !S.wsOrig?.getDuration()) return;
  const seg = S.detail.segmentation;
  S.drawing = true; // programmatic adds must not be mistaken for user-drawn regions
  S.regions.clearRegions();
  seg.speech.forEach(([a, b], i) => {
    const sel = i === S.selectedSpeech;
    const r = S.regions.addRegion({
      start: a, end: b, id: `speech-${i}`, drag: true, resize: true,
      color: sel ? css("--speech-sel") : css("--speech"),
    });
    r.element.title = `Speech ${fmt(a, 2)} – ${fmt(b, 2)} · drag to move, drag edges to resize, Alt+click or Delete to remove`;
    r.element.classList.toggle("sel", sel);
  });
  if (S.selectedSeg != null && seg.segments[S.selectedSeg]) {
    const { start, end } = seg.segments[S.selectedSeg];
    const r = S.regions.addRegion({ start, end, color: css("--accent-soft"), drag: false, resize: false, id: "selected" });
    r.element.style.pointerEvents = "none";
  }
  seg.cuts.forEach((c, i) => {
    const r = S.regions.addRegion({ start: c, color: css("--cut"), drag: true, resize: false, id: `cut-${i}` });
    r.element.title = `Cut at ${fmt(c, 2)} — drag to move, Alt+click or Delete to remove`;
    r.element.style.width = i === S.selectedCut ? "4px" : "2px";
    r.element.style.background = css("--cut");
    r.element.style.cursor = "ew-resize";
    r.element.style.opacity = i === S.selectedCut ? "1" : "0.85";
  });
  S.drawing = false;
}

// Every edit goes through putSeg, which keeps an undo stack of {cuts, speech} snapshots.
const UNDO_LIMIT = 100;
function applyDetail(d) {
  S.detail = { ...S.detail, ...d };
  S.detailVersion = d.version;
  drawRegions();
  renderSegments();
  drawVad();
  $("staleBadge").classList.toggle("hidden", !d.output_stale);
}
async function putSeg(body, { undoable = true } = {}) {
  const seg = S.detail.segmentation;
  if (undoable) {
    S.undo.push({ cuts: [...seg.cuts], speech: seg.speech.map((r) => [...r]) });
    if (S.undo.length > UNDO_LIMIT) S.undo.shift();
  }
  applyDetail(await api("PUT", `/api/files/${S.selected}/segmentation`, body));
}
const putCuts = (cuts) => putSeg({ cuts });
async function undo() {
  const snap = S.undo.pop();
  if (!snap) return;
  S.selectedCut = S.selectedSpeech = null;
  await putSeg(snap, { undoable: false });
}

function commitCutsFromRegions() {
  const cuts = S.regions.getRegions().filter((r) => r.id.startsWith("cut-")).map((r) => r.start);
  S.selectedCut = null;
  putCuts(cuts);
}

/** Speech = every region that is not a cut marker or the selected-segment overlay
 *  (includes regions the user just drew with drag-selection). */
function commitSpeechFromRegions() {
  const speech = S.regions.getRegions()
    .filter((r) => !r.id.startsWith("cut-") && r.id !== "selected" && r.end > r.start)
    .map((r) => [r.start, r.end]);
  S.selectedSpeech = null;
  putSeg({ speech });
}
function removeSpeech(i) {
  S.selectedSpeech = null;
  putSeg({ speech: S.detail.segmentation.speech.filter((_, k) => k !== i) });
}
function timeAtClient(clientX) {
  const wrapper = S.wsOrig.getWrapper();
  const rect = wrapper.getBoundingClientRect();
  return Math.min(S.detail.duration, Math.max(0, ((clientX - rect.left) / rect.width) * S.detail.duration));
}
function addCut(t) { putCuts([...S.detail.segmentation.cuts, t]); }
function removeCut(i) {
  S.selectedCut = null;
  putCuts(S.detail.segmentation.cuts.filter((_, k) => k !== i));
}

/** Cut a segment at its least speech-like point (smoothed VAD minimum), like the backend. */
function splitSegment(k) {
  const { start, end } = S.detail.segmentation.segments[k];
  const { probs, hop_s } = S.detail.vad;
  let best = (start + end) / 2, bestP = Infinity;
  for (let t = start + 0.5; t < end - 0.5; t += hop_s) {
    const i = Math.floor(t / hop_s);
    let p = 0;
    for (let j = -3; j <= 3; j++) p += probs[Math.min(probs.length - 1, Math.max(0, i + j))];
    if (p < bestP) { bestP = p; best = t; }
  }
  addCut(best);
}

// ------------------------------------------------------------------------------------
// segments table
// ------------------------------------------------------------------------------------
function selectSegAt(t) {
  const segs = S.detail?.segmentation?.segments || [];
  const k = segs.findIndex((s) => t >= s.start && t < s.end);
  if (k >= 0 && k !== S.selectedSeg) { S.selectedSeg = k; drawRegions(); renderSegments(); }
}

function renderSegments() {
  const d = S.detail;
  const segs = d.segmentation.segments;
  $("segCount").textContent = `(${segs.length})`;
  const body = $("segBody");
  body.innerHTML = "";
  segs.forEach((s, k) => {
    const tr = document.createElement("tr");
    tr.className = k === S.selectedSeg ? "selected" : "";
    const hasPrev = d.previews.includes(k);
    const pending = d.pending_previews.includes(k);
    tr.innerHTML = `
      <td>${k + 1}</td><td>${fmt(s.start, 2)}</td><td>${fmt(s.end, 2)}</td>
      <td>${(s.end - s.start).toFixed(1)} s</td>
      <td><span class="bar"><i style="width:${(s.speech * 100).toFixed(0)}%"></i></span>${(s.speech * 100).toFixed(0)}%</td>
      <td class="right"><span class="actions">
        <button data-act="orig" title="Play the original of this segment">▶ A</button>
        <button data-act="prev" title="${hasPrev ? "Play the enhanced preview" : "Enhance only this segment"}" ${pending ? "disabled" : ""}>
          ${pending ? '<span class="spin">◌</span>' : hasPrev ? "▶ B" : "✦ Preview"}</button>
        <button data-act="split" title="Split at the quietest point">✂</button>
        <button data-act="merge" title="Merge with next" ${k === segs.length - 1 ? "disabled" : ""}>⤓</button>
      </span></td>`;
    tr.onclick = (e) => {
      const act = e.target.closest("button")?.dataset.act;
      S.selectedSeg = k;
      if (!act) { syncTime(s.start); drawRegions(); renderSegments(); return; }
      e.stopPropagation();
      if (act === "orig") playOriginalSegment(k);
      if (act === "prev") hasPrev ? playPreview(k) : requestPreview(k);
      if (act === "split") splitSegment(k);
      if (act === "merge") removeCut(k);
    };
    body.appendChild(tr);
  });
}

function playOriginalSegment(k) {
  const { start, end } = S.detail.segmentation.segments[k];
  stopPreview();
  S.wsEnh?.pause();
  if (S.source !== "original") { S.source = "original"; updateAB(); }
  S.wsOrig.play(start, end);
  drawRegions();
  renderSegments();
}

async function requestPreview(k) {
  await api("POST", `/api/files/${S.selected}/preview/${k}`);
  S.detail.pending_previews.push(k);
  renderSegments();
}

function stopPreview() {
  if (S.previewAudio) { S.previewAudio.pause(); S.previewAudio = null; }
}
function playPreview(k) {
  stopPreview();
  S.wsOrig?.pause();
  S.wsEnh?.pause();
  S.previewAudio = new Audio(`/api/files/${S.selected}/audio/preview-${k}?v=${S.detailVersion}`);
  S.previewAudio.play();
}

// ------------------------------------------------------------------------------------
// actions
// ------------------------------------------------------------------------------------
$("playBtn").onclick = togglePlay;
$("addFilesBtn").onclick = () => api("POST", "/api/pick", { kind: "files" }).then(poll);
$("addFolderBtn").onclick = () => api("POST", "/api/pick", { kind: "folder" }).then(poll);
$("revealBtn").onclick = () => api("POST", `/api/files/${S.selected}/reveal`);
$("resegmentBtn").onclick = async () => {
  const seg = S.detail.segmentation;
  S.undo.push({ cuts: [...seg.cuts], speech: seg.speech.map((r) => [...r]) });
  const d = await api("POST", `/api/files/${S.selected}/resegment`);
  S.detail = { ...S.detail, ...d };
  S.detailVersion = d.version;
  S.selectedSeg = S.selectedCut = S.selectedSpeech = null;
  drawRegions(); renderSegments(); drawVad();
};
$("resetSpeechBtn").onclick = async () => {
  const seg = S.detail.segmentation;
  S.undo.push({ cuts: [...seg.cuts], speech: seg.speech.map((r) => [...r]) });
  S.selectedSpeech = null;
  applyDetail(await api("POST", `/api/files/${S.selected}/reset-speech`));
};
$("removeBtn").onclick = async () => {
  if (!confirm(`Remove “${S.detail.name}” from the list? The original file and outputs stay on disk.`)) return;
  await api("DELETE", `/api/files/${S.selected}`);
  S.selected = null;
  destroyWaves();
  $("detail").classList.add("hidden");
  $("emptyState").classList.remove("hidden");
  poll();
};
$("enhanceBtn").onclick = async () => {
  const f = S.files.find((x) => x.id === S.selected);
  if (f && ["enhancing", "queued"].includes(f.status)) await api("POST", `/api/files/${S.selected}/cancel`);
  else await api("POST", `/api/files/${S.selected}/enhance`);
  poll();
};

document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, select, textarea, dialog")) return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  else if (e.key === "b" || e.key === "B") switchSource(S.source === "original" ? "enhanced" : "original");
  else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
  else if ((e.key === "Delete" || e.key === "Backspace") && S.selectedSpeech != null) removeSpeech(S.selectedSpeech);
  else if ((e.key === "Delete" || e.key === "Backspace") && S.selectedCut != null) removeCut(S.selectedCut);
  else if (e.key === "Escape") { S.selectedCut = S.selectedSpeech = null; drawRegions(); }
  else if ((e.key === "s" || e.key === "S") && S.wsOrig) addCut(active().getCurrentTime());
});

// ------------------------------------------------------------------------------------
// settings
// ------------------------------------------------------------------------------------
$("settingsBtn").onclick = () => {
  const s = S.settings;
  if (!s) return;
  $("setOutput").value = s.output_dir;
  $("setBackend").value = s.backend;
  $("setMode").value = s.mode;
  $("setPrecision").value = s.precision;
  $("setTarget").value = s.target_s;
  $("setMax").value = s.max_s;
  $("setMin").value = s.min_s;
  $("settingsDlg").showModal();
};
$("pickOutputBtn").onclick = async () => {
  const r = await api("POST", "/api/pick", { kind: "output" });
  if (r.paths?.length) $("setOutput").value = r.paths[0];
};
$("saveSettingsBtn").onclick = () => {
  api("PUT", "/api/settings", {
    output_dir: $("setOutput").value,
    backend: $("setBackend").value,
    mode: $("setMode").value,
    precision: $("setPrecision").value,
    target_s: $("setTarget").value,
    max_s: $("setMax").value,
    min_s: $("setMin").value,
  }).then(poll);
};

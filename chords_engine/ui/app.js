"use strict";
/* ממשק זמני (אב-טיפוס) מעל ה-API של המנוע. הגרפיקאי יחליף את העיצוב — הלוגיקה מתועדת ב-docs/API.md */

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = t => { t = Math.max(0, t || 0); const m = Math.floor(t / 60), s = Math.floor(t % 60); return `${m}:${String(s).padStart(2, "0")}`; };
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { } },
};
const native = () => window.pywebview && window.pywebview.api;

async function api(method, path, body) {
  const r = await fetch("/api" + path, {
    method, headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || r.statusText);
  return data;
}
function toast(msg, ms = 2500) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), ms);
}
function confirmBox(text) {
  return new Promise(res => {
    $("cfText").textContent = text; const d = $("dlgConfirm"); d.showModal();
    $("cfOk").onclick = () => { d.close(); res(true); }; $("cfCancel").onclick = () => { d.close(); res(false); };
  });
}
function askText(title, value) {
  return new Promise(res => {
    $("txTitle").textContent = title; $("txInput").value = value ?? ""; const d = $("dlgText"); d.showModal();
    $("txInput").focus(); $("txInput").select();
    const done = v => { d.close(); res(v); };
    $("txOk").onclick = () => done($("txInput").value); $("txCancel").onclick = () => done(null);
    $("txInput").onkeydown = e => { if (e.key === "Enter") done($("txInput").value); };
  });
}

// ------------------------------------------------------------------ מצב
const S = {
  cfg: null, songs: [], jobs: [], lyricHits: null,
  view: "library", lib: { kind: "all", value: null, folder: "" },
  songId: null, song: null, edit: false, undo: [], redo: [], saveTimer: null,
  queue: [], qi: -1, shuffle: false, repeat: "off", playingId: null,
  loopA: null, loopB: null, rate: 1, dia: {},
  settings: Object.assign({ theme: "system", level: "normal", chordColor: "", markColor: "", font: "", lineH: 1.5 }, store.get("settings", {})),
};
const media = $("video");
media.preservesPitch = true;

const VIEW_DEFAULTS = { transpose: 0, capo: 0, simplify: "standard", notation: "letters", accidentals: "auto", mode: "above", font: 20 };
const viewOf = id => Object.assign({}, VIEW_DEFAULTS, store.get("view:" + id, {}));
const saveView = () => S.songId && store.set("view:" + S.songId, S.v);
const LEVELS = {
  fast: { skip_lyrics: true },
  normal: {},
  accurate: { accurate_timing: true },
};

// ------------------------------------------------------------------ ניווט
function show(view) {
  S.view = view;
  document.querySelectorAll(".nav").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  const target = ["library", "artists", "albums", "folders"].includes(view) ? "library" : view;
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === "v-" + target));
  if (target === "library") { if (view !== "library" || S.lib.kind === "all") S.lib = { kind: view === "library" ? "all" : view, value: null, folder: "" }; renderLibrary(); }
  if (view === "queue") renderQueue();
  if (view === "song") drawWave();
}
document.querySelectorAll(".nav").forEach(b => b.onclick = () => show(b.dataset.view));

// ------------------------------------------------------------------ ספרייה
async function loadSongs() {
  S.songs = await api("GET", "/songs");
  if (S.view !== "song") renderLibrary();
}
function jobFor(id) { return S.jobs.find(j => j.song_id === id && (j.status === "running" || j.status === "queued")); }
function stateBadge(s) {
  const j = jobFor(s.id);
  if (j) return `<span class="badge run">מנתח ${Math.round(j.progress * 100)}%</span>`;
  if (s.state !== "done") return `<span class="badge err">לא הושלם</span>`;
  return s.has_lyrics ? "" : `<span class="badge">בלי מילים</span>`;
}
function coverHtml(s, cls = "cover") {
  return s && s.has_cover ? `<div class="${cls}" style="background-image:url('/api/songs/${s.id}/cover')"></div>` : `<div class="${cls}">🎵</div>`;
}
function filteredSongs() {
  let list = S.songs;
  const q = $("search").value.trim().toLowerCase();
  const L = S.lib;
  if (L.kind === "artists" && L.value != null) list = list.filter(s => (s.artist || "") === L.value);
  if (L.kind === "albums" && L.value != null) list = list.filter(s => (s.album || "") === L.value);
  if (L.kind === "folders") list = list.filter(s => (s.folder || "") === L.folder);
  if (q) {
    const hits = new Set(S.lyricHits || []);
    list = S.songs.filter(s => [s.title, s.artist, s.album, s.folder, s.genre].join(" ").toLowerCase().includes(q) || hits.has(s.id));
  }
  if (L.kind === "albums" && L.value != null) list = [...list].sort((a, b) => (+a.track || 0) - (+b.track || 0));
  return list;
}
function songTable(list) {
  if (!list.length) return `<div class="empty">אין כאן שירים עדיין.<br><button class="primary" onclick="addFiles()">＋ הוספת שירים</button></div>`;
  return `<table class="songs"><thead><tr><th></th><th>שם</th><th>אמן</th><th>אלבום</th><th>סולם</th><th>משך</th><th></th><th></th></tr></thead><tbody>` +
    list.map((s, i) => `<tr data-id="${s.id}" class="${s.id === S.playingId ? "playing" : ""}">
      <td style="width:40px">${coverHtml(s, "cover")}</td>
      <td>${esc(s.title)}${s.is_video ? " 🎬" : ""}</td><td>${esc(s.artist)}</td><td>${esc(s.album)}</td>
      <td dir="ltr">${esc(s.key || "")}</td><td>${fmt(s.duration)}</td><td>${stateBadge(s)}</td>
      <td class="rowbtns"><button data-act="play" title="נגן">▶</button><button data-act="queue" title="הוסף לתור">＋</button><button data-act="move" title="העבר לתיקייה">📁</button><button data-act="del" title="מחק מהספרייה">🗑</button></td></tr>`).join("") + `</tbody></table>`;
}
function renderLibrary() {
  const L = S.lib, body = $("libBody"), crumbs = $("crumbs");
  const titles = { all: "ספרייה", artists: "אמנים", albums: "אלבומים", folders: "תיקיות" };
  $("libTitle").textContent = titles[L.kind];
  crumbs.innerHTML = "";
  const q = $("search").value.trim();
  if (!q && L.kind === "artists" && L.value == null) {
    const g = groupBy(S.songs, s => s.artist || "");
    body.innerHTML = `<div class="cards">${[...g].map(([a, l]) => `<div class="card" data-artist="${esc(a)}"><div class="cover">👤</div><b>${esc(a || "אמן לא ידוע")}</b><div class="muted small">${l.length} שירים</div></div>`).join("")}</div>`;
    body.querySelectorAll("[data-artist]").forEach(c => c.onclick = () => { S.lib.value = c.dataset.artist; renderLibrary(); });
    return;
  }
  if (!q && L.kind === "albums" && L.value == null) {
    const g = groupBy(S.songs, s => s.album || "");
    body.innerHTML = `<div class="cards">${[...g].map(([a, l]) => { const c = l.find(s => s.has_cover); return `<div class="card" data-album="${esc(a)}">${coverHtml(c)}<b>${esc(a || "בלי אלבום")}</b><div class="muted small">${esc(l[0].artist || "")} · ${l.length} שירים</div></div>`; }).join("")}</div>`;
    body.querySelectorAll("[data-album]").forEach(c => c.onclick = () => { S.lib.value = c.dataset.album; renderLibrary(); });
    return;
  }
  let head = "";
  if (L.value != null && L.kind !== "folders") crumbs.innerHTML = `<a data-back>${titles[L.kind]}</a> › ${esc(L.value || "לא ידוע")}`;
  if (!q && L.kind === "folders") {
    const parts = L.folder ? L.folder.split("/") : [];
    crumbs.innerHTML = [`<a data-f="">📁 כל התיקיות</a>`, ...parts.map((p, i) => `<a data-f="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</a>`)].join(" › ");
    const subs = new Set();
    for (const s of S.songs) {
      const f = s.folder || "";
      if (f && (L.folder === "" || f.startsWith(L.folder + "/"))) {
        const rest = L.folder ? f.slice(L.folder.length + 1) : f; if (rest) subs.add(rest.split("/")[0]);
      }
    }
    head = `<div class="foldertree">${[...subs].sort().map(n => `<div class="folder" data-f="${esc(L.folder ? L.folder + "/" + n : n)}">📁 ${esc(n)}</div>`).join("")}</div>`;
  }
  body.innerHTML = head + songTable(filteredSongs());
  crumbs.querySelectorAll("[data-back]").forEach(a => a.onclick = () => { S.lib.value = null; renderLibrary(); });
  body.querySelectorAll("[data-f]").forEach(a => a.onclick = () => { S.lib.folder = a.dataset.f; renderLibrary(); });
  crumbs.querySelectorAll("[data-f]").forEach(a => a.onclick = () => { S.lib.folder = a.dataset.f; renderLibrary(); });
  body.querySelectorAll("tr[data-id]").forEach(tr => {
    tr.onclick = e => {
      const act = e.target.dataset.act, id = tr.dataset.id;
      if (act === "play") { S.queue = filteredSongs().map(s => s.id); playAt(S.queue.indexOf(id)); }
      else if (act === "queue") { S.queue.push(id); toast("נוסף לתור"); }
      else if (act === "move") moveToFolder(id);
      else if (act === "del") deleteSong(id);
      else openSong(id);
    };
    tr.ondblclick = () => { S.queue = filteredSongs().map(s => s.id); playAt(S.queue.indexOf(tr.dataset.id)); };
  });
}
function groupBy(list, key) {
  const m = new Map();
  for (const s of list) { const k = key(s); if (!m.has(k)) m.set(k, []); m.get(k).push(s); }
  return new Map([...m].sort((a, b) => a[0].localeCompare(b[0], "he")));
}
let searchT;
$("search").oninput = () => {
  clearTimeout(searchT);
  searchT = setTimeout(async () => {
    const q = $("search").value.trim();
    S.lyricHits = q.length > 1 ? await api("GET", "/search?q=" + encodeURIComponent(q)).catch(() => []) : null;
    if (S.view === "song") show("library"); else renderLibrary();
  }, 250);
};
async function moveToFolder(id) {
  const s = S.songs.find(x => x.id === id);
  const f = await askText("תיקייה (אפשר תתי-תיקיות עם /)", s.folder || S.lib.folder || "");
  if (f == null) return;
  await api("PUT", "/songs/" + id, { meta: { folder: f.replace(/^\/+|\/+$/g, "") } });
  loadSongs();
}
async function deleteSong(id) {
  if (!await confirmBox("למחוק את השיר מהספרייה? (קובץ השמע עצמו לא יימחק)")) return;
  await api("DELETE", "/songs/" + id);
  if (S.songId === id) { S.songId = null; S.song = null; $("navSong").disabled = true; }
  loadSongs();
}

// ------------------------------------------------------------------ הוספת שירים
let pendingImport = null;
async function addFiles() {
  if (native()) {
    const paths = await native().pick_files();
    if (paths && paths.length) openImport({ paths });
  } else $("fileInput").click();
}
async function addFolder() {
  if (!native()) return toast("בחירת תיקייה זמינה רק בחלון התוכנה");
  const paths = await native().pick_folder();
  if (paths && paths.length) openImport({ paths, folder: true });
}
$("btnAddFiles").onclick = addFiles; $("btnAddFolder").onclick = addFolder;
$("fileInput").onchange = e => { if (e.target.files.length) openImport({ files: [...e.target.files] }); e.target.value = ""; };
function openImport(src) {
  pendingImport = src;
  const names = src.paths ? src.paths.map(p => p.split(/[\\/]/).pop()) : src.files.map(f => f.name);
  $("impFiles").textContent = (src.folder ? "תיקייה: " : "") + names.slice(0, 6).join(", ") + (names.length > 6 ? ` ועוד ${names.length - 6}` : "");
  $("impLevel").value = S.settings.level;
  $("impFolder").value = S.lib.kind === "folders" ? S.lib.folder : "";
  $("dlgImport").showModal();
}
$("impCancel").onclick = () => $("dlgImport").close();
$("impGo").onclick = async () => {
  const src = pendingImport; $("dlgImport").close();
  const options = Object.assign({}, LEVELS[$("impLevel").value]);
  let paths = src.paths;
  try {
    if (src.files) {
      paths = [];
      for (const f of src.files) {
        toast("מעתיק " + f.name);
        const r = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": encodeURIComponent(f.name) }, body: f });
        const d = await r.json(); if (!r.ok) throw new Error(d.error); paths.push(d.path);
      }
    }
    const jobs = await api("POST", "/library/import", { paths, options, folder: $("impFolder").value.trim() });
    toast(`${jobs.length} שירים נוספו לתור הניתוח`);
    pollJobs();
    if (jobs.length === 1) waitAndOpen(jobs[0].id);
  } catch (e) { toast("שגיאה: " + e.message, 5000); }
};
async function waitAndOpen(jobId) {
  for (let i = 0; i < 600; i++) {
    const j = await api("GET", "/jobs/" + jobId).catch(() => null);
    if (!j || j.status === "error" || j.status === "cancelled") return j && j.error && toast("שגיאה: " + j.error, 6000);
    if (j.song_id) { await loadSongs(); return openSong(j.song_id); }
    await new Promise(r => setTimeout(r, 700));
  }
}
// גרירה
let dragDepth = 0;
window.addEventListener("dragenter", e => { if (e.dataTransfer.types.includes("Files")) { dragDepth++; $("dropHint").classList.add("show"); } });
window.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("dropHint").classList.remove("show"); } });
window.addEventListener("dragover", e => e.preventDefault());
window.addEventListener("drop", e => {
  e.preventDefault(); dragDepth = 0; $("dropHint").classList.remove("show");
  if (window.__nativeDrop) return;      // החלון המקורי מעביר נתיבים מלאים דרך onNativeDrop
  const files = [...e.dataTransfer.files];
  if (files.length) openImport({ files });
});
window.onNativeDrop = paths => { if (paths && paths.length) openImport({ paths, folder: paths.length === 1 && !/\.\w{2,4}$/.test(paths[0]) }); };

// ------------------------------------------------------------------ עבודות ברקע
let pollT = null;
async function pollJobs() {
  clearTimeout(pollT);
  try {
    const prev = new Map(S.jobs.map(j => [j.id, j]));
    S.jobs = await api("GET", "/jobs");
    const active = S.jobs.filter(j => j.status === "running" || j.status === "queued");
    $("jobs").innerHTML = active.map(j => `<div class="job" data-song="${j.song_id || ""}"><div class="ellipsis">${esc(j.path.split(/[\\/]/).pop())}</div>
      <div class="muted">${j.status === "queued" ? "ממתין בתור" : esc(j.stage_label)} · ${Math.round(j.progress * 100)}%</div>
      <div class="progress"><div style="width:${j.progress * 100}%"></div></div></div>`).join("");
    $("jobs").querySelectorAll(".job").forEach(el => el.onclick = () => el.dataset.song && openSong(el.dataset.song));
    let libDirty = false;
    for (const j of S.jobs) {
      const p = prev.get(j.id);
      if (!p || p.status !== j.status || p.partial !== j.partial || p.song_id !== j.song_id) libDirty = true;
      if (j.song_id && j.song_id === S.songId && (!p || p.partial !== j.partial || (p.status !== j.status && j.status === "done"))) reloadSong();
      if (p && p.status === "running" && j.status === "error") toast("הניתוח נכשל: " + j.error, 7000);
    }
    if (libDirty) loadSongs();
    if (S.song) renderBanner();
    pollT = setTimeout(pollJobs, active.length ? 1000 : 4000);
  } catch { pollT = setTimeout(pollJobs, 3000); }
}

// ------------------------------------------------------------------ שיר
async function openSong(id) {
  if (S.songId !== id) { S.undo = []; S.redo = []; setEdit(false); }
  S.songId = id; S.v = viewOf(id);
  $("navSong").disabled = false;
  await reloadSong(true);
  show("song");
  if (!S.playingId || media.paused && S.playingId !== id) loadMedia(id, false);
}
async function reloadSong(scrollTop) {
  if (!S.songId) return;
  const q = new URLSearchParams({ transpose: S.v.transpose, capo: S.v.capo, simplify: S.v.simplify, notation: S.v.notation, accidentals: S.v.accidentals });
  const sc = $("v-song").scrollTop;
  try { S.song = await api("GET", `/songs/${S.songId}?${q}`); }
  catch (e) { toast(e.message); return; }
  renderSong();
  $("v-song").scrollTop = scrollTop ? 0 : sc;
}
function renderSong() {
  const d = S.song, m = d.meta;
  $("sTitle").textContent = m.title || "ללא שם";
  $("sArtist").textContent = [m.artist, m.album, m.year].filter(Boolean).join(" · ") || "אמן לא ידוע";
  $("cover").outerHTML = coverHtml({ id: d.id, has_cover: m.has_cover }, "cover big").replace('class="cover big"', 'id="cover" class="cover big"');
  $("sKey").textContent = m.key || "?";
  $("sKey").dir = "ltr";
  $("sKeyOrig").textContent = S.v.transpose ? ` (מקור: ${m.key_original})` : (m.key_confidence < 0.4 && m.key ? " (לא ודאי)" : "");
  $("sBpm").textContent = m.tempo ? Math.round(m.tempo * (S.playingId === d.id ? S.rate : 1)) : "?";
  $("sCapoInfo").innerHTML = S.v.capo ? `קאפו <b>${S.v.capo}</b> · אצבוע בסולם <b dir="ltr">${m.shape_key}</b>` : "";
  $("tVal").textContent = (S.v.transpose > 0 ? "+" : "") + S.v.transpose;
  $("capo").innerHTML = Array.from({ length: 12 }, (_, i) => `<option value="${i}">${i === 0 ? "בלי" : i}${d.capo_suggestions && d.capo_suggestions[0] && d.capo_suggestions[0].capo === i && i ? " ★" : ""}</option>`).join("");
  $("capo").value = S.v.capo;
  const best = (d.capo_suggestions || [])[0];
  $("capoHint").textContent = best && best.capo !== S.v.capo ? `הצעה: קאפו ${best.capo}${best.hard_chords.length ? " (קשה: " + best.hard_chords.join(", ") + ")" : " — הכל פתוח"}` : "";
  $("simplify").value = S.v.simplify; $("notation").value = S.v.notation; $("accidentals").value = S.v.accidentals; $("mode").value = S.v.mode;
  document.documentElement.style.setProperty("--sheet-size", S.v.font + "px");
  const done = d.analysis_state === "done";
  $("btnEdit").disabled = !done; $("btnLyrics").disabled = !done || !(d.recognized_words || []).length && d.lyrics_source === "none";
  $("btnReset").disabled = !done;
  $("video").classList.toggle("hidden", !(d.source.is_video && S.playingId === d.id && [".mp4", ".m4v", ".webm"].includes(d.source.ext)));
  renderBanner();
  renderSheet($("sheet"), d, false);
  renderDiagrams();
  drawWave();
  lastActive = {};
}
function renderBanner() {
  const d = S.song; if (!d) return;
  const j = jobFor(d.id), b = $("analysisBanner");
  if (d.analysis_state === "done" && !j) { b.classList.add("hidden"); return; }
  b.classList.remove("hidden");
  if (!j) {
    $("abStage").textContent = "הניתוח של השיר הזה לא הושלם"; $("abPct").textContent = ""; $("abCancel").textContent = "נתח מחדש";
    $("abCancel").onclick = reanalyze; $("abBar").style.width = "0"; $("abBlocks").innerHTML = ""; return;
  }
  $("abStage").textContent = j.status === "queued" ? "ממתין בתור לניתוח" : j.stage_label + "…";
  $("abPct").textContent = Math.round(j.progress * 100) + "%";
  $("abBar").style.width = j.progress * 100 + "%";
  $("abCancel").textContent = "ביטול"; $("abCancel").onclick = () => api("POST", `/jobs/${j.id}/cancel`).then(pollJobs);
  const dur = d.meta.duration || 0, until = d.transcribed_until || 0, n = Math.ceil(dur / 30);
  const lyricsStage = j.stage === "lyrics" || j.stage === "align";
  $("abBlocks").innerHTML = (d.timeline.length ? `<span class="done">✓ אקורדים</span>` : `<span class="${j.stage === "chords" ? "cur" : "wait"}">${j.stage === "chords" ? "●" : "○"} אקורדים</span>`) +
    (j.stages.some(s => s.id === "lyrics") ? Array.from({ length: n }, (_, i) => {
      const a = i * 30, e = Math.min(dur, a + 30);
      const cls = until >= e - 0.5 ? "done" : lyricsStage && until >= a ? "cur" : "wait";
      return `<span class="${cls}">${{ done: "✓", cur: "●", wait: "○" }[cls]} ${fmt(a)}–${fmt(e)}</span>`;
    }).join("") : "");
}

// ------------------------------------------------------------------ דף האקורדים
function sectionTitle(sec) {
  const n = { verse: "בית", chorus: "פזמון", intro: "פתיחה", interlude: "מעבר", outro: "סיום", instrumental: "נגינה" }[sec.kind] || sec.kind;
  return (sec.kind === "verse" || sec.kind === "chorus") && sec.number ? `${n} ${sec.number}` : n;
}
function renderSheet(el, d, stage) {
  const mode = stage ? "above" : S.v.mode;
  el.className = "sheet" + (stage ? " stagesheet" : "") + (mode === "lyrics" ? " mode-lyrics" : "");
  const secs = new Map((d.sections || []).map(s => [s.id, s]));
  let html = "", cur = undefined;
  d.lines.forEach((ln, li) => {
    if (ln.section !== cur) {
      if (cur !== undefined) html += `</div>`;
      cur = ln.section; const sec = secs.get(cur);
      html += `<div class="section">` + (sec ? `<div class="sechead"><span>${esc(sectionTitle(sec))}</span>` +
        (stage ? "" : `<button data-loopsec="${esc(sec.id)}" title="לופ על הקטע">🔁</button>`) +
        (!stage && S.edit ? `<select data-seckind="${esc(sec.id)}">${["verse", "chorus", "intro", "interlude", "outro"].map(k => `<option value="${k}" ${k === sec.kind ? "selected" : ""}>${sectionTitle({ kind: k })}</option>`).join("")}</select>` : "") + `</div>` : "");
    }
    html += `<div class="line" data-li="${li}" data-start="${ln.start}">` + (stage ? "" : lineOps(ln, li)) + `<div class="body">${lineHtml(ln, li, mode)}</div></div>`;
  });
  if (cur !== undefined) html += `</div>`;
  if (!d.lines.length) html = `<div class="pending">${d.analysis_state === "done" ? "לא זוהו אקורדים או מילים." : "האקורדים והמילים יופיעו כאן תוך כדי הניתוח…"}</div>`;
  else if (d.analysis_state !== "done" && d.analysis_state !== "media") html += `<div class="pending">${d.analysis_state === "chords" ? "האקורדים מוכנים — אפשר לנגן. המילים בדרך…" : "ממשיך לתמלל…"}</div>`;
  el.innerHTML = html;
  if (!stage) bindSheet(el);
}
function lineOps(ln, li) {
  return `<div class="lineops">${ln.type === "lyric" ? `<button data-op="text" data-li="${li}" title="עריכת טקסט">✎</button><button data-op="merge" data-li="${li}" title="איחוד עם השורה הבאה">⤓</button>` : ""}
    <button data-op="add" data-li="${li}" title="שורה חדשה אחרי זו">＋</button><button data-op="del" data-li="${li}" title="מחיקת השורה">🗑</button></div>`;
}
function lineHtml(ln, li, mode) {
  if (ln.type === "instrumental") {
    const cells = [];
    ln.chords.forEach((c, ci) => {
      const bars = Math.min(8, Math.max(1, Math.round((c.beats || 4) / 4)));
      const barLen = (c.duration || 0) / bars;
      for (let b = 0; b < bars; b++) cells.push(`<span class="bar1 c" data-li="${li}" data-ci="${ci}" data-time="${(c.time + b * barLen).toFixed(2)}">${b ? "%" : esc(c.name)}</span>`);
    });
    return `<div class="inst">${cells.join("")}</div>`;
  }
  const text = ln.text || "", chords = [...ln.chords].map((c, ci) => ({ ...c, ci })).sort((a, b) => a.char - b.char);
  if (mode === "chords") return `<div class="chordsonly">${chords.filter(c => !c.carried || chords.length === 1).map(c => `<span class="c" data-li="${li}" data-ci="${c.ci}" data-time="${c.time}">${esc(c.name)}</span>`).join("")}</div>`;
  // מיפוי אות -> מילה (להדגשת קריוקי)
  const wordAt = new Array(text.length).fill(-1);
  (ln.words || []).forEach((w, wi) => { for (let k = 0; k < w.text.length && w.char + k < text.length; k++) wordAt[w.char + k] = wi; });
  const low = new Set((ln.words || []).map((w, wi) => (w.p < 0.5 ? wi : -1)));
  const piece = (a, b) => {
    let out = "", i = a;
    while (i < b) {
      let j = i + 1; while (j < b && wordAt[j] === wordAt[i]) j++;
      const wi = wordAt[i];
      out += `<span class="w${low.has(wi) && wi >= 0 ? " low" : ""}" data-w="${wi}" data-c="${i}" data-li="${li}">${esc(text.slice(i, j))}</span>`;
      i = j;
    }
    return out;
  };
  if (mode === "inline") {
    let out = "", pos = 0;
    for (const c of chords) { out += piece(pos, Math.min(c.char, text.length)); out += `<span class="c" data-li="${li}" data-ci="${c.ci}" data-time="${c.time}">[${esc(c.name)}]</span>`; pos = Math.min(c.char, text.length); }
    return `<div class="inline">${out + piece(pos, text.length)}</div>`;
  }
  const bounds = [...new Set([0, ...chords.map(c => Math.min(c.char, text.length))])].sort((a, b) => a - b);
  let out = "";
  bounds.forEach((a, k) => {
    const b = k + 1 < bounds.length ? bounds[k + 1] : text.length;
    const here = chords.filter(c => Math.min(c.char, text.length) === a);
    const lab = here.map(c => `<span class="c${c.carried ? " carried" : ""}" data-li="${li}" data-ci="${c.ci}" data-time="${c.time}">${esc(c.name)}</span>`).join(" ");
    out += `<span class="seg"><span class="cwrap">${lab || `<span class="c">&nbsp;</span>`}</span><span class="t">${piece(a, b) || "&nbsp;"}</span></span>`;
  });
  return `<div class="lyr">${out}</div>`;
}
function bindSheet(el) {
  el.querySelectorAll("[data-loopsec]").forEach(b => b.onclick = e => { e.stopPropagation(); loopSection(b.dataset.loopsec); });
  el.querySelectorAll("[data-seckind]").forEach(s => s.onchange = () => {
    pushUndo(); const sec = S.song.sections.find(x => x.id === s.dataset.seckind); sec.kind = s.value; renderSheet($("sheet"), S.song, false); scheduleSave();
  });
  el.querySelectorAll("[data-op]").forEach(b => b.onclick = e => { e.stopPropagation(); lineOp(b.dataset.op, +b.dataset.li); });
  el.onpointerdown = sheetPointerDown;
  el.ondblclick = e => { if (!S.edit) return; const l = e.target.closest(".line"); if (l && S.song.lines[+l.dataset.li].type === "lyric") lineOp("text", +l.dataset.li); };
}

// קליק רגיל: קפיצה בנגן. במצב עריכה: לחיצה על אקורד = חלון, גרירה = הזזה, לחיצה על אות = הוספה
let drag = null;
function sheetPointerDown(e) {
  const c = e.target.closest(".c[data-ci]"), w = e.target.closest("[data-c]");
  if (!S.edit) {
    const t = c ? +c.dataset.time : w ? wordTime(+w.dataset.li, +w.dataset.w) : null;
    if (t != null && !isNaN(t)) seekSong(t);
    return;
  }
  if (c) {
    drag = { li: +c.dataset.li, ci: +c.dataset.ci, x: e.clientX, y: e.clientY, el: c, moved: false };
    document.addEventListener("pointermove", dragMove); document.addEventListener("pointerup", dragUp, { once: true });
    e.preventDefault();
  } else if (w || e.target.closest(".t")) {
    const pos = charFromPoint(e.clientX, e.clientY);
    if (pos) editChord({ li: pos.li, char: pos.char });
  }
}
function dragMove(e) { if (drag && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 5) { drag.moved = true; drag.el.classList.add("dragging"); } }
function dragUp(e) {
  document.removeEventListener("pointermove", dragMove);
  const d = drag; drag = null; if (!d) return;
  d.el.classList.remove("dragging");
  if (!d.moved) return editChord({ li: d.li, ci: d.ci });
  const pos = charFromPoint(e.clientX, e.clientY); if (!pos) return;
  const src = S.song.lines[d.li], dst = S.song.lines[pos.li];
  if (src.type !== "lyric" || dst.type !== "lyric") return;
  pushUndo();
  const [ch] = src.chords.splice(d.ci, 1);
  ch.char = pos.char; ch.carried = false;
  if (src !== dst) ch.time = wordTimeAtChar(dst, pos.char);
  dst.chords.push(ch);
  afterEdit();
}
function charFromPoint(x, y) {
  const r = document.caretRangeFromPoint ? document.caretRangeFromPoint(x, y) : null;
  let el = r && r.startContainer.nodeType === 3 ? r.startContainer.parentElement : document.elementFromPoint(x, y);
  const w = el && el.closest("[data-c]");
  if (w) return { li: +w.dataset.li, char: +w.dataset.c + (r && r.startContainer.parentElement === w ? r.startOffset : 0) };
  const line = el && el.closest(".line");
  if (line) return { li: +line.dataset.li, char: 0 };
  return null;
}
function wordTime(li, wi) { const ln = S.song.lines[li]; return ln && ln.words && ln.words[wi] ? ln.words[wi].start : ln && ln.start; }
function wordTimeAtChar(ln, ch) { const w = (ln.words || []).filter(w => w.char <= ch).pop(); return w ? w.start : ln.start; }

// ------------------------------------------------------------------ עריכה
function setEdit(on) {
  S.edit = on; document.body.classList.toggle("editing", on);
  $("btnEdit").classList.toggle("on", on); $("btnEdit").textContent = on ? "✓ סיום עריכה" : "✏️ עריכה";
  if (S.song) renderSheet($("sheet"), S.song, false);
}
$("btnEdit").onclick = () => setEdit(!S.edit);
function snapshot() { return JSON.stringify({ lines: S.song.lines, sections: S.song.sections, view: { transpose: S.v.transpose, capo: S.v.capo } }); }
function pushUndo() { S.undo.push(snapshot()); if (S.undo.length > 100) S.undo.shift(); S.redo = []; }
function restore(snap) { const s = JSON.parse(snap); S.song.lines = s.lines; S.song.sections = s.sections; saveNow(s.view); }
$("btnUndo").onclick = () => { if (!S.undo.length) return; S.redo.push(snapshot()); restore(S.undo.pop()); };
$("btnRedo").onclick = () => { if (!S.redo.length) return; S.undo.push(snapshot()); restore(S.redo.pop()); };
function afterEdit() { renderSheet($("sheet"), S.song, false); scheduleSave(); }
function scheduleSave() { $("sSaved").textContent = "…"; clearTimeout(S.saveTimer); S.saveTimer = setTimeout(() => saveNow(), 700); }
async function saveNow(view) {
  clearTimeout(S.saveTimer);
  const body = {
    view: view || { transpose: S.v.transpose, capo: S.v.capo },
    sections: S.song.sections,
    lines: S.song.lines.map(l => ({ id: l.id, type: l.type, role: l.role, section: l.section, start: l.start, end: l.end, text: l.text, words: l.words, stanza_break: l.stanza_break, chords: l.chords.map(c => ({ name: c.name, char: c.char, time: c.time, carried: c.carried, duration: c.duration, beats: c.beats })) })),
  };
  try {
    const sc = $("v-song").scrollTop;
    const v = await api("PUT", "/songs/" + S.songId, body);
    if (view && (view.transpose !== S.v.transpose || view.capo !== S.v.capo)) await reloadSong(); else { S.song = v; renderSong(); }
    $("v-song").scrollTop = sc;
    $("sSaved").textContent = "✓ נשמר";
  } catch (e) { $("sSaved").textContent = "⚠ לא נשמר"; toast("שמירה נכשלה: " + e.message, 5000); }
}
async function lineOp(op, li) {
  const lines = S.song.lines, ln = lines[li];
  if (op === "text") {
    const t = await askText("טקסט השורה", ln.text); if (t == null) return;
    pushUndo(); ln.text = t.trim(); ln.chords.forEach(c => c.char = Math.min(c.char, ln.text.length)); delete ln.words;
  } else if (op === "add") {
    const t = await askText("שורה חדשה", ""); if (t == null) return;
    pushUndo(); lines.splice(li + 1, 0, { type: "lyric", text: t.trim(), chords: [], start: ln.end, end: ln.end + 2, section: ln.section, stanza_break: false });
  } else if (op === "del") {
    pushUndo(); lines.splice(li, 1);
  } else if (op === "merge") {
    const nx = lines.slice(li + 1).findIndex(l => l.type === "lyric"); if (nx < 0) return;
    const b = lines[li + 1 + nx]; if (nx !== 0) return toast("אפשר לאחד רק עם שורת מילים צמודה");
    pushUndo(); const off = ln.text.length + 1;
    ln.chords.push(...b.chords.filter(c => !c.carried).map(c => ({ ...c, char: c.char + off })));
    ln.text = ln.text + " " + b.text; ln.end = b.end; delete ln.words; lines.splice(li + 1, 1);
  }
  afterEdit();
}

// חלון אקורד
let chordCtx = null, vocab = null;
async function editChord(ctx) {
  chordCtx = ctx;
  if (!vocab) vocab = await api("GET", "/chords/vocabulary");
  const ln = S.song.lines[ctx.li]; const cur = ctx.ci != null ? ln.chords[ctx.ci] : null;
  const flats = S.v.accidentals === "flats" || (S.v.accidentals === "auto" && /b/.test(S.song.meta.shape_key || ""));
  $("chTitle").textContent = cur ? "החלפת אקורד" : "הוספת אקורד";
  $("chDel").classList.toggle("hidden", !cur);
  $("chRoots").innerHTML = vocab.roots.map(r => `<button data-root="${flats ? r.flat : r.sharp}">${flats ? r.flat : r.sharp}</button>`).join("");
  $("chQual").innerHTML = vocab.qualities.map(q => `<button data-suffix="${esc(q.suffix)}">${q.suffix || "מז'ור"}</button>`).join("");
  $("chBass").innerHTML = `<option value="">—</option>` + vocab.roots.map(r => `<option>${flats ? r.flat : r.sharp}</option>`).join("");
  const parts = { root: "C", suffix: "", bass: "" };
  const lastName = cur ? cur.name : (ln.chords.filter(c => c.char <= ctx.char).pop() || {}).name;
  if (lastName) {
    const info = await api("GET", "/chord?name=" + encodeURIComponent(lastName) + (flats ? "&accidentals=flats" : "")).catch(() => null);
    if (info) { const m = info.name.match(/^([A-G][#b]?)(.*?)(?:\/([A-G][#b]?))?$/); if (m) { parts.root = m[1]; parts.suffix = m[2]; parts.bass = m[3] || ""; } }
  }
  const upd = async () => {
    $("chRoots").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.root === parts.root));
    $("chQual").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.suffix === parts.suffix));
    $("chBass").value = parts.bass;
    $("chText").value = parts.root + parts.suffix + (parts.bass ? "/" + parts.bass : "");
    await preview($("chText").value);
  };
  $("chRoots").onclick = e => { if (e.target.dataset.root) { parts.root = e.target.dataset.root; upd(); } };
  $("chQual").onclick = e => { if (e.target.dataset.suffix !== undefined) { parts.suffix = e.target.dataset.suffix; upd(); } };
  $("chBass").onchange = () => { parts.bass = $("chBass").value; upd(); };
  $("chText").oninput = () => preview($("chText").value);
  await upd();
  $("dlgChord").showModal();
}
async function preview(name) {
  try {
    const info = await api("GET", "/chord?name=" + encodeURIComponent(name));
    $("chErr").textContent = "";
    $("chPreview").innerHTML = `<div class="big">${esc(name)}</div>` + (info.guitar[0] ? guitarSvg(info.guitar[0]) : "") + pianoSvg(info.piano);
    return true;
  } catch (e) { $("chErr").textContent = e.message; $("chPreview").innerHTML = ""; return false; }
}
$("chCancel").onclick = () => $("dlgChord").close();
$("chOk").onclick = async () => {
  const name = $("chText").value.trim();
  if (!await preview(name)) return;
  $("dlgChord").close();
  pushUndo();
  const ln = S.song.lines[chordCtx.li];
  if (chordCtx.ci != null) Object.assign(ln.chords[chordCtx.ci], { name, carried: false });
  else ln.chords.push({ name, char: chordCtx.char, time: wordTimeAtChar(ln, chordCtx.char), carried: false });
  afterEdit();
};
$("chDel").onclick = () => {
  $("dlgChord").close(); pushUndo();
  S.song.lines[chordCtx.li].chords.splice(chordCtx.ci, 1); afterEdit();
};

// מילים
$("btnLyrics").onclick = () => {
  const d = S.song;
  let text = d.lyrics_text;
  if (!text) {
    let prev = null; const out = [];
    for (const l of d.lines) { if (l.type !== "lyric") continue; if (prev !== null && l.section !== prev) out.push(""); out.push(l.text); prev = l.section; }
    text = out.join("\n");
  }
  $("lyText").value = text; $("dlgLyrics").showModal();
};
$("lyCancel").onclick = () => $("dlgLyrics").close();
async function sendLyrics(text) {
  $("dlgLyrics").close(); pushUndo();
  try { S.song = await api("POST", `/songs/${S.songId}/lyrics`, { text, view: S.v }); renderSong(); toast("המילים יושרו לשיר"); }
  catch (e) { toast(e.message, 5000); }
}
$("lyGo").onclick = () => sendLyrics($("lyText").value);
$("lyClear").onclick = () => sendLyrics("");

// פרטי שיר
$("sTitle").onclick = async () => { const t = await askText("שם השיר", S.song.meta.title); if (t != null) { await api("PUT", "/songs/" + S.songId, { meta: { title: t } }); reloadSong(); loadSongs(); } };
$("sArtist").onclick = async () => {
  const m = S.song.meta;
  for (const [k, lbl] of [["artist", "אמן"], ["album", "אלבום"], ["year", "שנה"], ["genre", "ז'אנר"], ["folder", "תיקייה"]]) {
    const v = await askText(lbl, m[k] || ""); if (v == null) break;
    if (v !== (m[k] || "")) await api("PUT", "/songs/" + S.songId, { meta: { [k]: v } });
  }
  reloadSong(); loadSongs();
};
$("sBpm").onclick = async () => { const t = await askText("BPM", Math.round(S.song.meta.tempo || 0)); if (t && +t > 0) { await api("PUT", "/songs/" + S.songId, { meta: { tempo: +t } }); reloadSong(); } };
$("sKey").onclick = async () => { const t = await askText("סולם (למשל Am, C, F#m)", S.song.meta.key); if (t) { try { await api("PUT", "/songs/" + S.songId, { meta: { key: t }, view: S.v }); reloadSong(); } catch (e) { toast(e.message); } } };

// סרגל כלים
function setV(patch) { Object.assign(S.v, patch); saveView(); reloadSong(); }
$("tUp").onclick = () => setV({ transpose: Math.min(11, S.v.transpose + 1) });
$("tDown").onclick = () => setV({ transpose: Math.max(-11, S.v.transpose - 1) });
$("tVal").onclick = () => setV({ transpose: 0 });
$("capo").onchange = () => setV({ capo: +$("capo").value });
$("capoHint").onclick = () => { const b = S.song.capo_suggestions[0]; if (b) setV({ capo: b.capo }); };
$("simplify").onchange = () => setV({ simplify: $("simplify").value });
$("notation").onchange = () => setV({ notation: $("notation").value });
$("accidentals").onchange = () => setV({ accidentals: $("accidentals").value });
$("mode").onchange = () => { S.v.mode = $("mode").value; saveView(); renderSheet($("sheet"), S.song, false); };
$("fontUp").onclick = () => { S.v.font = Math.min(44, S.v.font + 2); saveView(); document.documentElement.style.setProperty("--sheet-size", S.v.font + "px"); };
$("fontDown").onclick = () => { S.v.font = Math.max(12, S.v.font - 2); saveView(); document.documentElement.style.setProperty("--sheet-size", S.v.font + "px"); };
$("instrument").onchange = renderDiagrams;
async function reanalyze() {
  if (!await confirmBox("לנתח את השיר מחדש? עריכות ידניות יוחלפו.")) return;
  await api("POST", `/songs/${S.songId}/reanalyze`, { options: LEVELS[S.settings.level] });
  toast("נכנס לתור הניתוח"); pollJobs();
}
$("btnReanalyze").onclick = reanalyze;
$("btnReset").onclick = async () => { if (await confirmBox("לבטל את כל התיקונים ולחזור לתוצאת הזיהוי?")) { S.song = await api("POST", `/songs/${S.songId}/reset`, { view: S.v }); renderSong(); } };
$("btnShowFile").onclick = () => native() ? native().open_folder(S.song.source.path) : toast(S.song.source.path, 6000);

// ייצוא
document.querySelectorAll("[data-exp]").forEach(b => b.onclick = async () => {
  const f = b.dataset.exp;
  if (f === "pdf") return window.print();
  const q = new URLSearchParams({ format: f === "copy" ? "txt" : f, transpose: S.v.transpose, capo: S.v.capo, simplify: S.v.simplify, notation: S.v.notation, accidentals: S.v.accidentals });
  const r = await fetch(`/api/songs/${S.songId}/export?${q}`); let text = await r.text();
  text = text.replace(/^﻿/, "");
  if (f === "copy") { await navigator.clipboard.writeText(text); return toast("הועתק ללוח"); }
  const ext = { txt: "txt", chordpro: "cho", lrc: "lrc", csv: "csv", json: "json" }[f];
  const name = `${S.song.meta.title || "song"}.${ext}`;
  if (native()) { const p = await native().save_file(name, text); if (p) toast("נשמר: " + p); }
  else { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/plain" })); a.download = name; a.click(); }
});

// ------------------------------------------------------------------ דיאגרמות
function guitarSvg(sh) {
  const W = 80, H = 96, x0 = 12, y0 = 18, sw = 11, fh = 14, frets = 5;
  const base = sh.base_fret || 1;
  let s = `<svg viewBox="0 0 ${W} ${H}" direction="ltr">`;
  s += base === 1 ? `<rect x="${x0}" y="${y0 - 3}" width="${sw * 5}" height="3" fill="currentColor"/>` : `<text x="${x0 - 3}" y="${y0 + 10}" font-size="9" text-anchor="end" fill="currentColor">${base}</text>`;
  for (let i = 0; i <= frets; i++) s += `<line x1="${x0}" x2="${x0 + sw * 5}" y1="${y0 + i * fh}" y2="${y0 + i * fh}" stroke="currentColor" stroke-opacity=".4"/>`;
  for (let i = 0; i < 6; i++) s += `<line x1="${x0 + i * sw}" x2="${x0 + i * sw}" y1="${y0}" y2="${y0 + frets * fh}" stroke="currentColor" stroke-opacity=".6"/>`;
  if (sh.barre) {
    const idx = sh.frets.map((f, i) => f === sh.barre ? i : -1).filter(i => i >= 0);
    const y = y0 + (sh.barre - base + .5) * fh;
    s += `<rect x="${x0 + idx[0] * sw - 4}" y="${y - 4}" width="${(idx[idx.length - 1] - idx[0]) * sw + 8}" height="8" rx="4" fill="var(--chord)"/>`;
  }
  sh.frets.forEach((f, i) => {
    const x = x0 + i * sw;
    if (f === null) s += `<text x="${x}" y="${y0 - 6}" font-size="9" text-anchor="middle" fill="currentColor">✕</text>`;
    else if (f === 0) s += `<circle cx="${x}" cy="${y0 - 9}" r="3" fill="none" stroke="currentColor"/>`;
    else s += `<circle cx="${x}" cy="${y0 + (f - base + .5) * fh}" r="4.3" fill="var(--chord)"/>`;
  });
  return s + `</svg>`;
}
function pianoSvg(notes) {
  if (!notes || !notes.length) return "";
  const lo = Math.floor(Math.min(...notes.map(n => n.midi)) / 12) * 12, hi = lo + 24;
  const on = new Map(notes.map(n => [n.midi, n.role]));
  const whites = [], blacks = [];
  for (let m = lo; m < hi; m++) ([1, 3, 6, 8, 10].includes(m % 12) ? blacks : whites).push(m);
  const ww = 7, W = whites.length * ww;
  let s = `<svg viewBox="0 0 ${W} 34" direction="ltr">`;
  whites.forEach((m, i) => s += `<rect x="${i * ww}" y="0" width="${ww}" height="34" fill="${on.has(m) ? "var(--chord)" : "#fff"}" stroke="#888" stroke-width=".5"/>`);
  blacks.forEach(m => {
    const i = whites.filter(w => w < m).length;
    s += `<rect x="${i * ww - 2.3}" y="0" width="4.6" height="20" fill="${on.has(m) ? "var(--chord)" : "#222"}"/>`;
  });
  return s + `</svg>`;
}
function renderDiagrams() {
  const inst = $("instrument").value, list = (S.song && S.song.chords_used) || [];
  $("diagrams").innerHTML = list.map((c, i) => {
    const k = S.dia[c.name] || 0, sh = c.guitar[k % Math.max(1, c.guitar.length)];
    const body = inst === "piano" ? pianoSvg(c.piano) : sh ? guitarSvg(sh) : `<div class="muted small">אין אצבוע</div>`;
    return `<div class="dia" data-i="${i}" data-name="${esc(c.name)}"><div class="n">${esc(c.name)}</div>${body}${inst === "guitar" && c.guitar.length > 1 ? `<div class="alt">${k % c.guitar.length + 1}/${c.guitar.length} ↻</div>` : ""}</div>`;
  }).join("");
  $("diagrams").querySelectorAll(".dia").forEach(d => d.onclick = () => { S.dia[d.dataset.name] = (S.dia[d.dataset.name] || 0) + 1; renderDiagrams(); });
}

// ------------------------------------------------------------------ צורת גל
function drawWave() {
  const cv = $("waveCanvas"), d = S.song; if (!d || !cv.offsetWidth) return;
  const dpr = devicePixelRatio || 1, W = cv.offsetWidth, H = cv.offsetHeight;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const css = getComputedStyle(document.documentElement), dur = d.meta.duration || 1;
  const X = t => W - (t / dur) * W;       // ימין-לשמאל: תחילת השיר בצד ימין
  const wf = d.waveform || [], mid = (H - 18) / 2;
  g.fillStyle = css.getPropertyValue("--muted");
  wf.forEach((v, i) => { const x = W - (i / wf.length) * W; g.fillRect(x - 1, mid - v * mid, Math.max(1, W / wf.length - .3), v * mid * 2 || 1); });
  if (S.loopA != null && S.playingId === d.id) { g.fillStyle = "rgba(47,111,237,.15)"; const b = S.loopB ?? S.loopA; g.fillRect(X(b), 0, X(S.loopA) - X(b), H); }
  g.font = "11px Segoe UI";
  for (const t of d.timeline || []) {
    const x1 = X(t.start), x2 = X(t.end);
    g.fillStyle = css.getPropertyValue("--line"); g.fillRect(x2, H - 16, 1, 16);
    if (x1 - x2 > 26 && t.name !== "N.C.") { g.fillStyle = css.getPropertyValue("--chord"); g.textAlign = "center"; g.fillText(t.name, (x1 + x2) / 2, H - 4); }
  }
  g.fillStyle = css.getPropertyValue("--accent");
  for (const s of d.sections || []) g.fillRect(X(s.start), 0, 1, H - 18);
  if (S.playingId === d.id) { g.fillStyle = "#e33"; g.fillRect(X(media.currentTime) - 1, 0, 2, H); }
}
$("wave").onclick = e => { const r = $("wave").getBoundingClientRect(); seekSong((1 - (e.clientX - r.left) / r.width) * S.song.meta.duration); };
window.addEventListener("resize", drawWave);

// ------------------------------------------------------------------ נגן
function summaryOf(id) { return S.songs.find(s => s.id === id) || (S.song && S.song.id === id ? { id, title: S.song.meta.title, artist: S.song.meta.artist, has_cover: S.song.meta.has_cover, tempo: S.song.meta.tempo } : { id }); }
function loadMedia(id, autoplay) {
  if (S.playingId !== id) {
    S.playingId = id; S.loopA = S.loopB = null; updateLoop();
    media.src = `/api/songs/${id}/audio`; media.playbackRate = S.rate;
    const s = summaryOf(id);
    $("pTitle").textContent = s.title || ""; $("pArtist").textContent = s.artist || "";
    $("pCover").outerHTML = coverHtml(s, "cover").replace('class="cover"', 'id="pCover" class="cover"');
    if (S.song && S.song.id === id) renderSong();
    if (S.view !== "song") renderLibrary();
  }
  if (autoplay) media.play().catch(e => toast("לא ניתן לנגן: " + e.message));
}
function seekSong(t) {
  if (S.playingId !== S.songId) loadMedia(S.songId, false);
  const go = () => { media.currentTime = t; if (media.paused) media.play(); };
  media.readyState >= 1 ? go() : media.addEventListener("loadedmetadata", go, { once: true });
}
function playAt(i) {
  if (i < 0 || i >= S.queue.length) return;
  S.qi = i; loadMedia(S.queue[i], true);
  if (S.view === "queue") renderQueue();
}
function next(auto) {
  if (S.repeat === "one" && auto) { media.currentTime = 0; return media.play(); }
  if (!S.queue.length) return;
  let i = S.shuffle ? Math.floor(Math.random() * S.queue.length) : S.qi + 1;
  if (i >= S.queue.length) { if (S.repeat === "all") i = 0; else return; }
  playAt(i);
}
$("pPlay").onclick = () => {
  if (!S.playingId) { if (S.songId) return loadMedia(S.songId, true); const l = filteredSongs(); if (l.length) { S.queue = l.map(s => s.id); playAt(0); } return; }
  media.paused ? media.play() : media.pause();
};
$("pStop").onclick = () => { media.pause(); media.currentTime = 0; };
$("pNext").onclick = () => next(false);
$("pPrev").onclick = () => media.currentTime > 3 ? (media.currentTime = 0) : playAt(Math.max(0, S.qi - 1));
$("pShuffle").onclick = () => { S.shuffle = !S.shuffle; $("pShuffle").classList.toggle("on", S.shuffle); };
$("pRepeat").onclick = () => {
  S.repeat = { off: "all", all: "one", one: "off" }[S.repeat];
  $("pRepeat").classList.toggle("on", S.repeat !== "off"); $("pRepeat").textContent = S.repeat === "one" ? "🔂" : "🔁";
  toast({ off: "בלי חזרה", all: "חזרה על התור", one: "חזרה על השיר" }[S.repeat]);
};
media.onplay = () => { $("pPlay").textContent = "⏸"; $("stPlay").textContent = "⏸"; };
media.onpause = () => { $("pPlay").textContent = "▶"; $("stPlay").textContent = "▶"; };
media.onended = () => next(true);
media.onloadedmetadata = () => { $("pDur").textContent = fmt(media.duration); };
media.onerror = () => S.playingId && toast("לא ניתן לנגן את הקובץ (הוזז או פורמט לא נתמך)", 5000);
$("pSeek").oninput = () => { if (media.duration) media.currentTime = $("pSeek").value / 1000 * media.duration; };
$("pVol").oninput = () => { media.volume = $("pVol").value / 100; media.muted = false; $("pMute").textContent = "🔊"; };
$("pMute").onclick = () => { media.muted = !media.muted; $("pMute").textContent = media.muted ? "🔇" : "🔊"; };
function setRate(r) {
  S.rate = Math.round(Math.min(1.5, Math.max(0.5, r)) * 100) / 100; media.playbackRate = S.rate; media.preservesPitch = true;
  $("rateVal").textContent = Math.round(S.rate * 100) + "%";
  const s = summaryOf(S.playingId); $("bpmNow").textContent = s.tempo ? `${Math.round(s.tempo * S.rate)} BPM` : "";
  if (S.song && S.playingId === S.song.id) $("sBpm").textContent = Math.round(S.song.meta.tempo * S.rate);
}
$("rateUp").onclick = () => setRate(S.rate + .05); $("rateDown").onclick = () => setRate(S.rate - .05); $("rateVal").onclick = () => setRate(1);
// לופ
$("loopA").onclick = () => { S.loopA = media.currentTime; if (S.loopB != null && S.loopB <= S.loopA) S.loopB = null; updateLoop(); };
$("loopB").onclick = () => { if (S.loopA == null) S.loopA = 0; if (media.currentTime > S.loopA) S.loopB = media.currentTime; updateLoop(); };
function loopSection(id) {
  const sec = S.song.sections.find(s => s.id === id); if (!sec) return;
  if (S.playingId !== S.songId) loadMedia(S.songId, false);
  S.loopA = sec.start; S.loopB = sec.end; updateLoop(); seekSong(sec.start); toast("לופ על " + sectionTitle(sec));
}
function updateLoop() {
  $("loopA").classList.toggle("on", S.loopA != null); $("loopB").classList.toggle("on", S.loopB != null);
  $("loopInfo").innerHTML = S.loopA != null ? `${fmt(S.loopA)}→${S.loopB != null ? fmt(S.loopB) : "…"} <a href="#" id="loopX">✕</a>` : "";
  const x = $("loopX"); if (x) x.onclick = e => { e.preventDefault(); S.loopA = S.loopB = null; updateLoop(); };
  drawWave();
}

// ------------------------------------------------------------------ סנכרון עם הנגינה
let lastActive = {};
function findIdx(arr, t, key) { let lo = 0, hi = arr.length - 1, r = -1; while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m][key] <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; }
function tick() {
  requestAnimationFrame(tick);
  if (!S.playingId) return;
  const t = media.currentTime;
  if (S.loopA != null && S.loopB != null && t >= S.loopB) media.currentTime = S.loopA;
  if (media.duration) { $("pSeek").value = t / media.duration * 1000; $("pCur").textContent = fmt(t); }
  const d = S.song;
  if (!d || d.id !== S.playingId) return;
  const tl = d.timeline || [], i = findIdx(tl, t + 0.05, "start");
  const cur = i >= 0 && t < tl[i].end ? tl[i].name : "–";
  const nxt = tl.slice(i + 1).find(x => x.name !== "N.C." && x.name !== cur);
  if (cur !== lastActive.cur || (nxt && nxt.name) !== lastActive.nxt) {
    lastActive.cur = cur; lastActive.nxt = nxt && nxt.name;
    $("curChord").textContent = cur; $("nextChord").textContent = nxt ? nxt.name : "–";
    $("stCur").textContent = cur; $("stNext").textContent = nxt ? nxt.name : "–";
    document.querySelectorAll(".dia").forEach(el => el.classList.toggle("hl", el.dataset.name === cur));
  }
  if (!drawWave._t || performance.now() - drawWave._t > 100) { drawWave._t = performance.now(); drawWave(); }
  const stage = !$("stage").classList.contains("hidden");
  const root = stage ? $("stSheet") : $("sheet");
  const li = findIdx(d.lines, t + 0.15, "start");
  const key = (stage ? "s" : "m") + li;
  if (key !== lastActive.line) {
    root.querySelectorAll(".line.active").forEach(e => e.classList.remove("active"));
    const el = root.querySelector(`.line[data-li="${li}"]`);
    if (el) { el.classList.add("active"); if ($("autoscroll").checked || stage) el.scrollIntoView({ block: "center", behavior: "smooth" }); }
    lastActive.line = key;
  }
  if (li < 0) return;
  const ln = d.lines[li];
  let ci = -1; ln.chords.forEach((c, k) => { if (c.time <= t + 0.05 && (ci < 0 || c.time >= ln.chords[ci].time)) ci = k; });
  const wi = ln.words ? ln.words.findIndex(w => w.start <= t && t < w.end) : -1;
  const ak = `${key}:${ci}:${wi}`;
  if (ak !== lastActive.inner) {
    lastActive.inner = ak;
    root.querySelectorAll(".c.active, .w.active").forEach(e => e.classList.remove("active"));
    const lineEl = root.querySelector(`.line[data-li="${li}"]`); if (!lineEl) return;
    if (ln.type === "instrumental") {
      const bars = [...lineEl.querySelectorAll(".bar1")]; const b = bars.filter(x => +x.dataset.time <= t + 0.05).pop(); if (b) b.classList.add("active");
    } else {
      if (ci >= 0) lineEl.querySelectorAll(`.c[data-ci="${ci}"]`).forEach(e => e.classList.add("active"));
      if (wi >= 0) lineEl.querySelectorAll(`.w[data-w="${wi}"]`).forEach(e => e.classList.add("active"));
    }
  }
}
requestAnimationFrame(tick);

// ------------------------------------------------------------------ תור
function renderQueue() {
  $("queueList").innerHTML = S.queue.length ? S.queue.map((id, i) => { const s = summaryOf(id); return `<div class="qitem ${i === S.qi ? "cur" : ""}" data-i="${i}">
    <span>${i === S.qi ? "▶" : i + 1}</span><span class="t">${esc(s.title)} <span class="muted small">${esc(s.artist || "")}</span></span>
    <button data-q="up">▲</button><button data-q="down">▼</button><button data-q="rm">✕</button></div>`; }).join("") : `<div class="empty">התור ריק. ▶ או ＋ בספרייה מוסיפים שירים.</div>`;
  $("queueList").querySelectorAll(".qitem").forEach(el => el.onclick = e => {
    const i = +el.dataset.i, a = e.target.dataset.q;
    if (a === "rm") { S.queue.splice(i, 1); if (i < S.qi) S.qi--; }
    else if (a === "up" && i > 0) { [S.queue[i - 1], S.queue[i]] = [S.queue[i], S.queue[i - 1]]; if (S.qi === i) S.qi--; else if (S.qi === i - 1) S.qi++; }
    else if (a === "down" && i < S.queue.length - 1) { [S.queue[i + 1], S.queue[i]] = [S.queue[i], S.queue[i + 1]]; if (S.qi === i) S.qi++; else if (S.qi === i + 1) S.qi--; }
    else if (!a) playAt(i);
    renderQueue();
  });
}
$("qClear").onclick = () => { S.queue = S.qi >= 0 && S.playingId ? [S.playingId] : []; S.qi = S.queue.length ? 0 : -1; renderQueue(); };

// ------------------------------------------------------------------ מצב נגינה / הופעה
function openStage() {
  if (!S.song) return;
  if (S.playingId !== S.songId) loadMedia(S.songId, false);
  $("stTitle").textContent = S.song.meta.title;
  $("stage").classList.remove("hidden");
  renderSheet($("stSheet"), S.song, true);
  lastActive = {};
  native() && native().keep_awake(true);
}
function closeStage() { $("stage").classList.add("hidden"); lastActive = {}; native() && native().keep_awake(false); }
$("btnStage").onclick = openStage; $("stClose").onclick = closeStage;
$("stPlay").onclick = () => $("pPlay").onclick();
$("stMin").onclick = () => $("stage").classList.toggle("min");
$("stT-").onclick = async () => { await setV({ transpose: S.v.transpose - 1 }); };
$("stT+").onclick = async () => { await setV({ transpose: S.v.transpose + 1 }); };
$("stRate-").onclick = () => setRate(S.rate - .05); $("stRate+").onclick = () => setRate(S.rate + .05);
$("stFont-").onclick = () => $("fontDown").onclick(); $("stFont+").onclick = () => $("fontUp").onclick();
const _renderSong = renderSong;
renderSong = function () { _renderSong(); if (!$("stage").classList.contains("hidden")) renderSheet($("stSheet"), S.song, true); };

// ------------------------------------------------------------------ מקלדת
document.addEventListener("keydown", e => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || document.querySelector("dialog[open]");
  if (e.ctrlKey && e.key.toLowerCase() === "s") { e.preventDefault(); if (S.song && S.edit) saveNow(); return; }
  if (e.ctrlKey && e.key.toLowerCase() === "z" && S.edit && !typing) { e.preventDefault(); $("btnUndo").onclick(); return; }
  if (e.ctrlKey && e.key.toLowerCase() === "y" && S.edit && !typing) { e.preventDefault(); $("btnRedo").onclick(); return; }
  if (e.ctrlKey && e.key.toLowerCase() === "f") { e.preventDefault(); show("library"); $("search").focus(); return; }
  if (e.ctrlKey && e.key.toLowerCase() === "p" && S.song) { e.preventDefault(); show("song"); setTimeout(() => window.print(), 50); return; }
  if (typing) return;
  const k = e.key;
  if (k === " ") { e.preventDefault(); $("pPlay").onclick(); }
  else if (k === "ArrowLeft") { e.preventDefault(); media.currentTime += 5; }       // RTL: שמאלה = קדימה
  else if (k === "ArrowRight") { e.preventDefault(); media.currentTime -= 5; }
  else if (k === "ArrowUp" && S.song) { e.preventDefault(); $("tUp").onclick(); }
  else if (k === "ArrowDown" && S.song) { e.preventDefault(); $("tDown").onclick(); }
  else if (k.toLowerCase() === "l" || k === "ך") { if (S.loopA != null && S.loopB != null) { S.loopA = S.loopB = null; updateLoop(); } else if (S.loopA == null) $("loopA").onclick(); else $("loopB").onclick(); }
  else if (k.toLowerCase() === "e" || k === "ק") { if (S.song && !$("btnEdit").disabled) setEdit(!S.edit); }
  else if (k === "F11") { e.preventDefault(); if ($("stage").classList.contains("hidden")) openStage(); native() ? native().fullscreen() : document.documentElement.requestFullscreen?.(); }
  else if (k === "Escape" && !$("stage").classList.contains("hidden")) closeStage();
});

// ------------------------------------------------------------------ הגדרות
function applySettings() {
  const st = S.settings, root = document.documentElement;
  const dark = st.theme === "dark" || (st.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  root.dataset.theme = dark ? "dark" : "light";
  root.style.setProperty("--chord", st.chordColor || ""); if (!st.chordColor) root.style.removeProperty("--chord");
  if (st.markColor) root.style.setProperty("--mark", st.markColor); else root.style.removeProperty("--mark");
  if (st.font) root.style.setProperty("--font", st.font); else root.style.removeProperty("--font");
  root.style.setProperty("--line-h", st.lineH || 1.5);
  $("setTheme").value = st.theme; $("setLevel").value = st.level; $("setFont").value = st.font || "'Segoe UI', Arial"; $("setLine").value = st.lineH || 1.5;
  const css = getComputedStyle(root);
  $("setChordColor").value = toHex(st.chordColor || css.getPropertyValue("--chord").trim());
  $("setMarkColor").value = toHex(st.markColor || css.getPropertyValue("--mark").trim());
  drawWave();
}
function toHex(c) { return /^#[0-9a-f]{6}$/i.test(c) ? c : "#c2410c"; }
function saveSettings() { store.set("settings", S.settings); applySettings(); }
$("setTheme").onchange = () => { S.settings.theme = $("setTheme").value; saveSettings(); };
$("setLevel").onchange = () => { S.settings.level = $("setLevel").value; saveSettings(); };
$("setChordColor").oninput = () => { S.settings.chordColor = $("setChordColor").value; saveSettings(); };
$("setMarkColor").oninput = () => { S.settings.markColor = $("setMarkColor").value; saveSettings(); };
$("setFont").onchange = () => { S.settings.font = $("setFont").value; saveSettings(); };
$("setLine").oninput = () => { S.settings.lineH = +$("setLine").value; saveSettings(); };
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applySettings);

// ------------------------------------------------------------------ הפעלה
async function init() {
  applySettings();
  try {
    S.cfg = await api("GET", "/config");
    $("engineState").innerHTML = S.cfg.whisper_ready ? `מנוע ${S.cfg.version} · מודל עברית ✓` : `⚠ מודל העברית חסר — אפשר לנתח אקורדים בלבד`;
    $("sysInfo").innerHTML = `גרסה ${S.cfg.version}<br>מודלים: ${S.cfg.whisper_models.join(", ") || "אין"}<br>ספרייה: ${esc(S.cfg.library_dir)}`;
  } catch { $("engineState").textContent = "⚠ המנוע לא עונה"; }
  await loadSongs();
  show("library");
  pollJobs();
  setInterval(() => fetch("/api/ping").catch(() => { }), 10000);
  setRate(1);
}
init();

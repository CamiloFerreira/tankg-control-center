// Tank-G Control for Android (Chrome + Web MIDI over USB-OTG). Same model as the desktop app:
// `device` = last bank read from the pedal, `local` = working copy; "modified" = slots that
// differ. Every write takes a backup first (once per session), writes only changed slots and
// verifies by read-back.
import { AMP_MODELS, CAB_MODELS, FIELDS, LIBRARY } from "./data.js";
import { Bank, DeviceError, SLOTS, TankG, fakePedal, fromHex, midiAccess, openMidi, slotName, toHex } from "./protocol.js";

const $ = id => document.getElementById(id);
const F = Object.fromEntries(FIELDS.map(f => [f.key, f]));
// Same order and colours as the desktop pedal panel.
const MODULES = [
  { title: "GATE", cls: "m-gate", c: "--gate", faders: ["gate"] },
  { title: "AMP", cls: "m-amp", c: "--amp", sw: "amp_on", select: "amp_type", faders: ["gain", "treble", "middle", "bass", "volume"] },
  { title: "MOD", cls: "m-mod", c: "--mod", sw: "mod_on", faders: ["mod_fx", "mod_speed"] },
  { title: "DELAY", cls: "m-dly", c: "--dly", sw: "dly_on", faders: ["dly_mix", "dly_time"] },
  { title: "REVERB", cls: "m-rvb", c: "--rvb", sw: "rvb_on", faders: ["rvb_decay", "rvb_mix"] },
  { title: "CAB", cls: "m-cab", c: "--gate", select: "cab", faders: [] },
];
const DEMO_BANKS = ["Guitarra eléctrica", "Metallica", "Iron Maiden", "AC/DC", "Blind Guardian", "Korn",
  "Bajo limpio", "Guitarra clásica (nylon)", "Strato: limpios"];

const ANDROID = !!globalThis.AndroidMidi;   // running inside the APK (native MIDI bridge)
const S = { dev: null, demo: false, device: null, local: null, current: 0, undo: [], busy: false,
  backupDone: false, wanted: false, libBank: null, libPick: 0 };

// storage (per-viewer conveniences; everything still works if storage is blocked) ---------------

const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
const aliasKey = () => (S.demo ? "tankg.aliases.demo" : "tankg.aliases");
let aliases = { presets: {}, banks: {} };
const loadAliases = () => { aliases = store.get(aliasKey(), { presets: {}, banks: {} }); };
const saveAliases = () => store.set(aliasKey(), aliases);
const presetName = s => aliases.presets[slotName(s)] || "";
const bankName = b => aliases.banks[String(b + 1)] || "";
function setPresetName(s, name) {
  name = (name || "").trim();
  if (name) aliases.presets[slotName(s)] = name; else delete aliases.presets[slotName(s)];
  saveAliases();
}

// state helpers ------------------------------------------------------------------------------

const modified = () => (S.local && S.device ? S.local.diffSlots(S.device) : []);
const get = (key, s = S.current) => S.local.presets[s][F[key].offset];
const zoneOf = (f, v) => (f.zones.length ? f.zones[Math.min(2, Math.floor((v * 3) / (f.max + 1)))] : "");
const ampName = p => AMP_MODELS[p[F.amp_type.offset]] ?? "?";
const rgbHex = p => "#" + toHex(p.slice(18, 21));

function pushUndo() {
  S.undo.push({ bank: S.local.copy(), aliases: JSON.stringify(aliases) });
  if (S.undo.length > 100) S.undo.shift();
}

function toast(text, ms = 3500) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, ms);
}

// rendering ---------------------------------------------------------------------------------

function buildModules() {
  const root = $("modules");
  root.innerHTML = "";
  for (const m of MODULES) {
    const el = document.createElement("div");
    el.className = `module ${m.cls}`;
    el.style.setProperty("--c", `var(${m.c})`);
    el.innerHTML = `<div class="mhead"><b>${m.title}</b></div>`;
    if (m.sw) {
      const b = document.createElement("button");
      b.className = "switch";
      b.dataset.key = m.sw;
      b.setAttribute("aria-label", `${m.title} encendido/apagado`);
      b.onclick = () => { pushUndo(); setField(m.sw, get(m.sw) ? 0 : 1); };
      el.firstChild.append(b);
    }
    if (m.select) {
      const names = m.select === "amp_type" ? AMP_MODELS : CAB_MODELS;
      const wrap = document.createElement("div");
      wrap.className = m.select === "cab" ? "mbody" : "mselect";
      wrap.innerHTML = (m.select === "cab" ? '<span class="led"></span>' : "") + `<select data-key="${m.select}" aria-label="${m.title}">` +
        names.map((n, i) => `<option value="${i}">${m.select === "cab" ? (i ? `${i}. ${n}` : n) : `${i + 1}. ${n}`}</option>`).join("") +
        "</select>";
      wrap.querySelector("select").onchange = e => { pushUndo(); setField(m.select, +e.target.value); };
      el.append(wrap);
    }
    if (m.faders.length) {
      const row = document.createElement("div");
      row.className = "faders";
      for (const key of m.faders) row.append(makeFader(key));
      el.append(row);
    }
    root.append(el);
  }
}

/** Vertical fader. Dragging is relative (like a mixing desk): a tap never jumps the value. */
function makeFader(key) {
  const f = F[key];
  const el = document.createElement("div");
  el.className = "fader";
  el.dataset.fader = key;
  el.innerHTML = `<span class="led"></span><label>${f.label}</label>
    <div class="track" tabindex="0" role="slider" aria-label="${f.label}" aria-valuemin="0" aria-valuemax="${f.max}">
      <div class="fill"></div><div class="thumb"></div></div><output></output><small class="zone"></small>`;
  const track = el.querySelector(".track");
  let start = null;
  const apply = v => {
    v = Math.max(0, Math.min(f.max, Math.round(v)));
    if (v !== get(key)) { setField(key, v, false); paintFader(el, v); }
  };
  track.onpointerdown = e => {
    track.setPointerCapture(e.pointerId);
    pushUndo();
    start = { y: e.clientY, v: get(key), h: track.clientHeight };
    track.classList.add("active");
    e.preventDefault();
  };
  track.onpointermove = e => { if (start) apply(start.v + ((start.y - e.clientY) / start.h) * f.max); };
  track.onpointerup = track.onpointercancel = () => {
    if (!start) return;
    start = null;
    track.classList.remove("active");
    if (S.undo.length && S.undo.at(-1).bank.presets[S.current].every((b, i) => b === S.local.presets[S.current][i])) S.undo.pop();
    render();
  };
  track.onkeydown = e => {
    const step = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1, PageUp: 10, PageDown: -10 }[e.key];
    if (!step) return;
    e.preventDefault();
    pushUndo();
    apply(get(key) + step);
    render();
  };
  return el;
}

function paintFader(el, v) {
  const f = F[el.dataset.fader], pct = (v / f.max) * 100;
  el.querySelector(".fill").style.height = `${pct}%`;
  el.querySelector(".thumb").style.bottom = `calc(${pct}% - 11px)`;
  el.querySelector("output").textContent = v;
  el.querySelector(".zone").textContent = zoneOf(f, v);
  el.querySelector(".track").setAttribute("aria-valuenow", v);
}

function render() {
  const connected = !!S.dev;
  const st = $("status");
  st.textContent = S.demo ? "Demo" : connected ? "Conectada" : "Desconectada";
  st.className = "pill " + (S.demo ? "demo" : connected ? "on" : "off");
  $("connect").hidden = connected;
  const has = !!S.local;
  $("empty").hidden = has;
  $("editor").hidden = !has;
  $("bottom").hidden = !has;
  for (const id of ["tbRead", "tbSave", "tbUndo", "tbLib"]) $(id).disabled = !has;
  if (!has) return;

  const mod = new Set(modified());
  const cur = S.current, curBank = Math.floor(cur / 4), p = S.local.presets[cur];
  renderBrowser(mod);

  // header
  $("slotTag").textContent = slotName(cur);
  if (document.activeElement !== $("alias")) $("alias").value = presetName(cur);
  $("bankTag").textContent = `Banco ${curBank + 1}` + (bankName(curBank) ? ` · ${bankName(curBank)}` : "");
  $("modBadge").hidden = !mod.has(cur);
  $("revert").disabled = !mod.has(cur);
  $("saveOne").disabled = !mod.has(cur) || !connected;
  const [r, g, b] = p.slice(18, 21);
  $("led").value = rgbHex(p);
  $("led").parentElement.style.background = rgbHex(p);
  $("led").parentElement.style.setProperty("--led-ink", r * 0.299 + g * 0.587 + b * 0.114 > 140 ? "#111" : "#fff");

  // footswitches + display
  for (const btn of document.querySelectorAll(".foot")) {
    const s = curBank * 4 + +btn.dataset.i, q = S.local.presets[s];
    btn.classList.toggle("sel", s === cur);
    btn.style.borderColor = s === cur ? rgbHex(q) : "#3a3f45";
    btn.style.setProperty("--ring", rgbHex(q));
    const name = btn.parentElement.querySelector(".foot-name");
    name.textContent = presetName(s) || ampName(q);
    name.classList.toggle("mod", mod.has(s));
  }
  $("dispSlot").textContent = slotName(cur);
  $("dispBank").textContent = bankName(curBank) || `BANCO ${curBank + 1}`;

  // modules
  for (const m of MODULES) {
    const el = document.querySelector(`.${m.cls}`);
    const on = m.sw ? !!get(m.sw) : m.select === "cab" ? get("cab") > 0 : get("gate") > 0;
    el.classList.toggle("off", !on);
    for (const led of el.querySelectorAll(".led")) led.classList.toggle("on", on);
    const sw = el.querySelector(".switch");
    if (sw) { sw.textContent = on ? "ON" : "OFF"; sw.classList.toggle("on", on); }
    const sel = el.querySelector("select");
    if (sel) sel.value = get(sel.dataset.key);
    for (const fd of el.querySelectorAll(".fader")) paintFader(fd, get(fd.dataset.fader));
  }

  rememberDraft();
  updateActions(mod);
}

function updateActions(mod = new Set(modified())) {
  const connected = !!S.dev, n = mod.size;
  $("undo").disabled = $("tbUndo").disabled = !S.undo.length;
  $("save").disabled = $("tbSave").disabled = !n || !connected;
  $("save").textContent = n ? `Guardar (${n})` : "Guardar";
  $("tbSave").textContent = n ? `Guardar cambios (${n})` : "Guardar cambios";
  $("modBadge").hidden = !mod.has(S.current);
  $("saveOne").disabled = !mod.has(S.current) || !connected;
}

function renderBrowser(mod) {   // the 36 presets at a glance, like the desktop app
  const root = $("browserGrid");
  root.innerHTML = "";
  for (let b = 0; b < 9; b++) {
    const h = document.createElement("div");
    h.className = "bhead";
    h.textContent = `BANCO ${b + 1}` + (bankName(b) ? ` · ${bankName(b)}` : "");
    root.append(h);
    const row = document.createElement("div");
    row.className = "brow";
    for (let i = 0; i < 4; i++) {
      const s = b * 4 + i, p = S.local.presets[s];
      const c = document.createElement("button");
      c.className = "bslot" + (s === S.current ? " sel" : "") + (mod.has(s) ? " mod" : "");
      c.style.borderColor = s === S.current ? "#fff" : rgbHex(p);
      c.textContent = presetName(s) || ampName(p);
      c.title = `${slotName(s)} · ${ampName(p)}`;
      c.onclick = () => { select(s); closeBrowser(); };
      row.append(c);
    }
    root.append(row);
  }
}

const openBrowser = () => { if (!document.body.classList.contains("tablet")) document.body.classList.add("browsing"); };
const closeBrowser = () => document.body.classList.remove("browsing");

// phone / tablet view: automatic by width, or forced from the menu --------------------------
const VIEWS = { auto: "automática", phone: "teléfono", tablet: "tablet" };
let view = store.get("tankg.view", "auto");
const wide = matchMedia("(min-width: 760px) and (min-height: 560px)");   // phones in landscape keep the phone layout
function applyView() {
  const tablet = view === "tablet" || (view === "auto" && wide.matches);
  document.body.classList.toggle("tablet", tablet);
  if (tablet) closeBrowser();
  document.querySelector('[data-cmd="view"]').textContent = `Vista: ${VIEWS[view]}`;
  if (tablet && !$("libSheet").hidden && S.libBank) $("libList").hidden = false;
}
wide.addEventListener?.("change", applyView);

function select(slot) { S.current = slot; render(); }

function setField(key, value, full = true) {
  S.local.presets[S.current][F[key].offset] = value;
  if (full) render(); else updateActions();
}

/** Footswitch: select the preset and, like on the pedal, make it sound. */
function pressFoot(i) {
  const s = Math.floor(S.current / 4) * 4 + i;
  select(s);
  if (!S.dev) return;
  S.dev.selectPreset(s);
  toast(modified().includes(s) ? `${slotName(s)} activo · suena la versión guardada (tiene cambios sin guardar)`
    : `${slotName(s)} activo en la pedalera`, 2200);
}

// dialogs -----------------------------------------------------------------------------------

function modal({ title, step = "", rows = [], bar = false, ok = null, cancel = "Cerrar" }) {
  $("mTitle").textContent = title;
  $("mStep").textContent = step;
  $("mStep").className = "";
  $("mBar").hidden = !bar;
  $("mBar").firstElementChild.style.width = "0";
  $("mRows").innerHTML = "";
  for (const r of rows) {
    const d = document.createElement("div");
    d.textContent = r;
    d.className = "todo";
    $("mRows").append(d);
  }
  $("mOk").hidden = !ok;
  $("mOk").textContent = ok || "";
  $("mClose").textContent = cancel;
  $("mClose").disabled = false;
  $("modal").hidden = false;
}
const closeModal = () => { $("modal").hidden = true; };

function ask(title, text, ok = "Sí") {
  return new Promise(resolve => {
    modal({ title, step: text, ok, cancel: "Cancelar" });
    $("mOk").onclick = () => { closeModal(); resolve(true); };
    $("mClose").onclick = () => { closeModal(); resolve(false); };
  });
}

function info(title, text) {
  modal({ title, step: text });
  $("mClose").onclick = closeModal;
}

// pedal operations ----------------------------------------------------------------------------

async function connect(silent = false) {
  if (S.busy) return;
  S.busy = true;
  $("emptyError").textContent = "";
  try {
    const dev = await openMidi();
    const fromDemo = S.demo;
    S.dev = dev;
    S.demo = false;
    S.wanted = true;
    loadAliases();
    watchPorts(dev.access);
    adoptBank(dev.bank, fromDemo);
    toast(`Tank-G conectada (${S.dev.portName})`);
  } catch (e) {
    S.dev = null;
    if (!silent) {
      // Connect by itself as soon as the pedal is plugged in (permission is already granted).
      S.wanted = true;
      midiAccess().then(watchPorts).catch(() => {});
      if (S.local) info("No se pudo conectar", e.message); else $("emptyError").textContent = e.message;
    }
  } finally {
    S.busy = false;
    render();
  }
}

// Unsaved edits survive Android closing the app in the background: kept while they apply to the
// same pedal contents, dropped as soon as the pedal holds something else.
function rememberDraft() {
  if (S.demo || !S.local || !S.device) return;
  if (modified().length) store.set("tankg.draft", { device: toHex(S.device.toBytes()), local: toHex(S.local.toBytes()) });
  else store.set("tankg.draft", null);
}

function adoptBank(bank, fresh = false) {
  const draft = !S.local && store.get("tankg.draft", null);
  if (draft && draft.device === toHex(bank.toBytes())) {
    S.device = bank;
    S.local = Bank.fromBytes(fromHex(draft.local));
    toast(`Recuperados ${modified().length} cambios sin guardar`);
    return;
  }
  S.device = bank;
  // Keep unsaved edits across a reconnection of the same pedal, but never carry the demo bank
  // over to a real pedal: «Guardar» would overwrite it with demo presets.
  if (!S.local || fresh) {
    S.local = bank.copy();
    S.undo = [];
    S.backupDone = false;
  }
}

function watchPorts(access) {
  if (access.onstatechange) return;
  access.onstatechange = e => {
    if (S.demo) return;
    if (e.port.state === "disconnected" && S.dev && e.port.name === S.dev.portName) {
      S.dev = null;
      render();
      toast("Tank-G desconectada");
    } else if (e.port.state === "connected" && !S.dev && S.wanted) {
      setTimeout(() => connect(true), 800);   // the pedal needs a moment after plugging in
    }
  };
}

function startDemo() {
  const bank = new Bank(Array.from({ length: SLOTS }, () => new Uint8Array(21)));
  S.demo = true;
  loadAliases();
  DEMO_BANKS.forEach((name, b) => {
    const lib = LIBRARY.find(x => x.name === name) || LIBRARY[b];
    lib.presets.forEach((p, i) => {
      bank.presets[b * 4 + i] = fromHex(p.hex);
      aliases.presets[slotName(b * 4 + i)] = p.name;
    });
    aliases.banks[String(b + 1)] = lib.name;
  });
  saveAliases();
  const image = bank.toBytes();
  const dev = new TankG(fakePedal(image, { latency: 25 }));
  dev.portName = "Pedalera simulada";
  S.dev = dev;
  S.device = Bank.fromBytes(image);
  S.local = S.device.copy();
  S.undo = [];
  S.current = 0;
  render();
  toast("Modo demo: una pedalera simulada, nada sale del teléfono");
}

async function readDevice() {
  if (!S.dev) return connect();
  if (modified().length && !(await ask("Leer pedalera", "Hay cambios sin guardar. ¿Descartarlos y leer la pedalera?"))) return;
  if (S.busy) return;
  S.busy = true;
  try {
    const bank = await S.dev.readBank();
    if (S.local) pushUndo();
    S.device = bank;
    S.local = bank.copy();
    toast("Presets leídos de la pedalera");
  } catch (e) {
    info("Error", e.message);
  } finally {
    S.busy = false;
    render();
  }
}

function backup(bank, why) {
  const list = store.get("tankg.backups", []);
  list.unshift({ t: Date.now(), why, hex: toHex(bank.toBytes()) });
  store.set("tankg.backups", list.slice(0, 20));
}

async function upload(slots, selectSlot = null) {
  if (!slots.length || !S.dev) return false;
  if (S.busy) { toast("Hay una operación en curso"); return false; }
  S.busy = true;
  const target = S.local.copy();
  const names = slots.map(s => `${slotName(s)}  ${presetName(s)}`.trim());
  modal({ title: "Subiendo a la pedalera", step: "Preparando…", rows: names, bar: true });
  $("mClose").disabled = true;
  const rows = [...$("mRows").children];
  const total = slots.length;
  let done = 0;
  const mark = (n, failed = false) => rows.forEach((r, i) => {
    r.className = i < n ? "done" : i === n ? (failed ? "fail" : "cur") : "todo";
  });
  const step = (text, cls = "") => { $("mStep").textContent = text; $("mStep").className = cls; };
  try {
    if (!S.backupDone && !S.demo) {   // the demo pedal is simulated: nothing to back up
      step("Backup previo del banco…");
      backup(await S.dev.readBank(), "auto");
      S.backupDone = true;
    }
    const after = await S.dev.writePresets(target, slots, (n, t, s) => {
      done = n;
      mark(n);
      $("mBar").firstElementChild.style.width = `${(n / (t + 1)) * 100}%`;
      step(s === null ? "Verificando: releyendo la pedalera…"
        : `Subiendo ${n + 1} de ${t} · ${slotName(s)}${presetName(s) ? ` «${presetName(s)}»` : ""}…`);
    });
    S.device = after;
    if (selectSlot !== null) S.dev.selectPreset(selectSlot);
    mark(total);
    $("mBar").firstElementChild.style.width = "100%";
    step(`✓ ${total} preset${total > 1 ? "s" : ""} guardado${total > 1 ? "s" : ""} y verificado${total > 1 ? "s" : ""}`, "ok");
    $("mClose").onclick = closeModal;
    setTimeout(() => { if ($("mStep").className === "ok") closeModal(); }, 1500);
    return true;
  } catch (e) {
    mark(done, true);
    step(`✗ ${e instanceof DeviceError ? e.message : `Error inesperado: ${e.message}`}`, "bad");
    $("mClose").onclick = closeModal;
    return false;
  } finally {
    $("mClose").disabled = false;
    S.busy = false;
    render();
  }
}

async function saveAll() {
  const slots = modified();
  if (!slots.length) return;
  if (slots.length > 1 && !(await ask("Guardar en la pedalera",
    `Se sobrescribirán en la pedalera: ${slots.map(slotName).join(", ")}\n¿Continuar?`))) return;
  await upload(slots, slots.includes(S.current) ? S.current : null);
}

// library -------------------------------------------------------------------------------------

function openLibrary() {
  $("libSheet").hidden = false;
  showLibList();
  renderLibList();
}

function showLibList() {
  $("libList").hidden = false;
  $("libDetail").hidden = true;
  $("libTitle").textContent = "Biblioteca de sonidos";
}

function renderLibList() {
  const q = $("libSearch").value.trim().toLowerCase();
  const root = $("libBanks");
  root.innerHTML = "";
  let genre = null, count = 0;
  for (const b of LIBRARY) {
    const text = `${b.genre} ${b.name} ${b.presets.map(p => `${p.name} ${p.desc}`).join(" ")}`.toLowerCase();
    if (q && !text.includes(q)) continue;
    if (b.genre !== genre) {
      genre = b.genre;
      const h = document.createElement("div");
      h.className = "genre";
      h.textContent = genre.toUpperCase();
      root.append(h);
    }
    const item = document.createElement("button");
    item.className = "bank-item";
    item.innerHTML = "<b></b><small></small>";
    item.querySelector("b").textContent = b.name;
    item.querySelector("small").textContent = b.presets.map(p => p.role).join(" · ");
    item.onclick = () => showLibBank(b);
    root.append(item);
    count++;
  }
  if (!count) root.innerHTML = `<p class="muted">Nada coincide con «${q.replace(/[<>&]/g, "")}».</p>`;
}

function showLibBank(b) {
  S.libBank = b;
  S.libPick = 0;
  $("libList").hidden = !document.body.classList.contains("tablet");
  $("libDetail").hidden = false;
  $("libTitle").textContent = b.name;
  $("libDesc").textContent = b.genre;
  $("libUpload").checked = !!S.dev;
  $("libUpload").disabled = !S.dev;
  $("libDest").innerHTML = "";
  for (let i = 0; i < 9; i++) {
    const o = document.createElement("option");
    o.value = i;
    o.textContent = `Banco ${i + 1}` + (bankName(i) ? ` · ${bankName(i)}` : "");
    $("libDest").append(o);
  }
  $("libDest").value = Math.floor(S.current / 4);
  renderLibPresets();
}

function renderLibPresets() {
  const root = $("libPresets");
  root.innerHTML = "";
  S.libBank.presets.forEach((p, i) => {
    const c = document.createElement("button");
    const color = fromHex(p.hex).slice(18, 21);
    c.className = "pcard" + (i === S.libPick ? " sel" : "");
    c.style.setProperty("--c", `rgb(${color.join(",")})`);
    c.innerHTML = '<div class="role"></div><b></b><span></span><span></span>';
    c.querySelector(".role").textContent = `${"ABCD"[i]} · ${p.role.toUpperCase()}`;
    c.querySelector("b").textContent = p.name;
    const [d, s] = c.querySelectorAll("span");
    d.textContent = p.desc;
    s.textContent = p.summary;
    c.onclick = () => { S.libPick = i; renderLibPresets(); };
    root.append(c);
  });
  $("libOne").textContent = `Aplicar «${S.libBank.presets[S.libPick].name}» a ${slotName(S.current)}`;
}

async function applyPresets(first, items, bank = "") {
  pushUndo();
  const slots = items.map((it, i) => {
    S.local.presets[first + i] = Uint8Array.from(it.bytes);
    setPresetName(first + i, it.name);
    return first + i;
  });
  if (bank && items.length === 4 && first % 4 === 0) { aliases.banks[String(first / 4 + 1)] = bank; saveAliases(); }
  S.current = first;
  $("libSheet").hidden = true;
  render();
  const pending = slots.filter(s => modified().includes(s));
  if (!$("libUpload").checked || !S.dev) {
    toast(S.dev ? "Aplicado en el editor. Pulsa «Guardar» para subirlo." : "Aplicado. Conecta la pedalera y pulsa «Guardar».");
  } else if (!pending.length) {
    toast("Sin cambios: la pedalera ya tiene esos presets.");
  } else {
    await upload(pending, first);
  }
}

// backups -----------------------------------------------------------------------------------

function openBackups() {
  const list = store.get("tankg.backups", []);
  const root = $("bakList");
  root.innerHTML = list.length ? "" : '<p class="muted">Todavía no hay backups.</p>';
  for (const b of list) {
    const row = document.createElement("div");
    row.className = "bak";
    const when = new Date(b.t);
    row.innerHTML = `<div><b>${when.toLocaleString()}</b><small>${b.why}</small></div>`;
    const dl = document.createElement("button");
    dl.className = "btn small";
    dl.textContent = "Descargar";
    dl.onclick = () => {
      const z = n => String(n).padStart(2, "0");   // local time, like the desktop backups
      const stamp = `${when.getFullYear()}${z(when.getMonth() + 1)}${z(when.getDate())}-${z(when.getHours())}${z(when.getMinutes())}${z(when.getSeconds())}`;
      if (ANDROID) {
        const bytes = fromHex(b.hex);
        const where = globalThis.AndroidMidi.saveFile(`tankg-${stamp}.tgbank`, btoa(String.fromCharCode(...bytes)));
        toast(where ? `Guardado en ${where}` : "No se pudo guardar el archivo");
        return;
      }
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([fromHex(b.hex)], { type: "application/octet-stream" }));
      a.download = `tankg-${stamp}.tgbank`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    };
    const load = document.createElement("button");
    load.className = "btn small";
    load.textContent = "Al editor";
    load.disabled = !S.local;
    load.onclick = () => {
      pushUndo();
      S.local = Bank.fromBytes(fromHex(b.hex));
      $("bakSheet").hidden = true;
      render();
      toast("Backup cargado en el editor. «Guardar» lo pasa a la pedalera.");
    };
    row.append(dl, load);
    root.append(row);
  }
  $("bakSheet").hidden = false;
}

// wiring ------------------------------------------------------------------------------------

function wire() {
  $("connect").onclick = $("connectBig").onclick = () => connect();
  $("demoBig").onclick = startDemo;
  $("menuBtn").onclick = e => { e.stopPropagation(); $("menu").hidden = !$("menu").hidden; };
  document.addEventListener("click", () => { $("menu").hidden = true; });
  $("menu").onclick = e => {
    const cmd = e.target.dataset.cmd;
    if (cmd === "read") readDevice();
    if (cmd === "backups") openBackups();
    if (cmd === "demo") startDemo();
    if (cmd === "view") {
      view = { auto: "phone", phone: "tablet", tablet: "auto" }[view];
      store.set("tankg.view", view);
      applyView();
      toast(`Vista ${VIEWS[view]}`);
    }
    if (cmd === "about") info("Tank-G Control", "Editor de presets para la M-VAVE Tank-G.\n\nVersión web/Android de la app de " +
      "escritorio: mismo protocolo verificado, backup antes de escribir y verificación por relectura.\n\n" +
      (ANDROID ? "Conecta la pedalera por USB-OTG." : "Requiere Chrome y la pedalera conectada por USB-OTG."));
  };
  $("alias").onchange = () => { pushUndo(); setPresetName(S.current, $("alias").value); render(); };
  for (const f of document.querySelectorAll(".foot")) f.onclick = () => pressFoot(+f.dataset.i);
  $("bankDown").onclick = () => select((S.current + SLOTS - 4) % SLOTS);
  $("bankUp").onclick = () => select((S.current + 4) % SLOTS);
  $("display").onclick = openBrowser;
  $("browserClose").onclick = closeBrowser;
  $("saveOne").onclick = () => upload([S.current], S.current);
  $("tbRead").onclick = readDevice;
  $("revert").onclick = () => { pushUndo(); S.local.presets[S.current] = Uint8Array.from(S.device.presets[S.current]); render(); };
  $("led").onchange = e => {
    pushUndo();
    S.local.presets[S.current].set(fromHex(e.target.value.slice(1)), 18);
    render();
  };
  $("undo").onclick = $("tbUndo").onclick = () => {
    const u = S.undo.pop();
    if (!u) return;
    S.local = u.bank;
    aliases = JSON.parse(u.aliases);
    saveAliases();
    render();
  };
  $("save").onclick = $("tbSave").onclick = saveAll;
  $("library").onclick = $("tbLib").onclick = openLibrary;
  $("libSearch").oninput = renderLibList;
  for (const b of document.querySelectorAll("[data-close]")) b.onclick = () => {
    if (!$("libDetail").hidden && !$("libSheet").hidden && !document.body.classList.contains("tablet")) showLibList();
    else b.closest(".sheet").hidden = true;
  };
  $("libOne").onclick = () => {
    const p = S.libBank.presets[S.libPick];
    applyPresets(S.current, [{ bytes: fromHex(p.hex), name: p.name }]);
  };
  $("libBank").onclick = async () => {
    const dest = +$("libDest").value;
    if (!(await ask("Cargar banco", `Se reemplazarán los 4 presets del banco ${dest + 1} por «${S.libBank.name}».\n¿Continuar?`))) return;
    applyPresets(dest * 4, S.libBank.presets.map(p => ({ bytes: fromHex(p.hex), name: p.name })), S.libBank.name);
  };
  // Android back button: close the sheet instead of leaving the app
  history.replaceState({ root: true }, "");
  window.addEventListener("popstate", () => {
    const open = [...document.querySelectorAll(".sheet")].find(s => !s.hidden);
    if (open) { open.hidden = true; history.pushState({}, ""); }
    else if (document.body.classList.contains("browsing")) { closeBrowser(); history.pushState({}, ""); }
  });
  history.pushState({}, "");
}

buildModules();
wire();
loadAliases();
applyView();
render();
if (ANDROID) {
  // Native app: no permission prompt; connect now and whenever the pedal is plugged in.
  $("emptyHint").textContent = "Enchufa la pedalera al teléfono o tablet con un adaptador USB-OTG y enciéndela: se conecta sola.";
  S.wanted = true;
  midiAccess().then(watchPorts);
  connect(true);
} else {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  // Reconnect without a prompt when MIDI permission was already granted.
  navigator.permissions?.query({ name: "midi", sysex: true }).then(p => { if (p.state === "granted") connect(true); }).catch(() => {});
}

window.tankg = { S, connect, startDemo, upload, applyPresets };   // for debugging over adb

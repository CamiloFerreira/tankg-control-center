// Tank-G Control for Android (USB-OTG or Bluetooth, through MainActivity). Same model as the desktop app:
// `device` = last bank read from the pedal, `local` = working copy; "modified" = slots that
// differ. Every write takes a backup first (once per session), writes only changed slots and
// verifies by read-back.
import { AI, AMP_MODELS, BYTE_NAMES, CAB_MODELS, FACTORY, FACTORY_SETS, FIELDS, LEGAL, LIBRARY, RELEASES_REPO, VERSION } from "./data.js";
import { Bank, DeviceError, SLOTS, TankG, androidBluetoothPedals, fakePedal, fromHex, midiAccess, openMidi, slotName, toHex } from "./protocol.js";
import { fromText as aiFromText, generate as generateAI, webPrompt, zoneGap } from "./ai.js";
import { parseBankFile, parsePresetFile, parseSetFile, presetFile, setFile, stamp } from "./files.js";
import * as cloud from "./cloud.js";
import * as am4 from "./am4.js";

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

const A = globalThis.AndroidMidi;   // native bridge of MainActivity (MIDI, Bluetooth, files, updates)
const S = { dev: null, demo: false, device: null, local: null, current: 0, undo: [], busy: false,
  backupDone: false, wanted: false, libBank: null, libPick: 0, clipboard: null, live: false };

// storage (per-viewer conveniences; everything still works if storage is blocked) ---------------

const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
const aliasKey = () => (S.demo ? "tankg.aliases.demo" : "tankg.aliases");
let aliases = { presets: {}, banks: {}, amps: {} };
const loadAliases = () => { aliases = { presets: {}, banks: {}, amps: {}, ...store.get(aliasKey(), {}) }; };
const saveAliases = () => store.set(aliasKey(), aliases);
const presetName = s => aliases.presets[slotName(s)] || "";
const bankName = b => aliases.banks[String(b + 1)] || "";
/** TYPE entry: the uploaded model's name when the slot no longer holds the factory one. */
const ampLabel = i => `${i + 1}. ${aliases.amps?.[String(i + 1)] || AMP_MODELS[i]}`;
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
        names.map((n, i) => `<option value="${i}">${m.select === "cab" ? (i ? `${i}. ${n}` : n) : ampLabel(i)}</option>`).join("") +
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
    try { track.setPointerCapture(e.pointerId); } catch { /* synthetic events have no pointer to capture */ }
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
  el.querySelector(".zone").textContent = zoneGap(f, v) ? "APAGADO" : zoneOf(f, v);
  el.querySelector(".track").setAttribute("aria-valuenow", v);
}

function render() {
  const connected = !!S.dev;
  const st = $("status");
  st.textContent = S.demo ? "Demo" : connected ? (S.dev.bluetooth ? "Conectada · Bluetooth" : "Conectada") : "Desconectada";
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
    // like on the pedal, the knob lights go off when a three-zone knob sits between two zones
    const lit = on && !m.faders.some(k => zoneGap(F[k], get(k)));
    for (const led of el.querySelectorAll(".led")) led.classList.toggle("on", lit);
    const sw = el.querySelector(".switch");
    if (sw) { sw.textContent = on ? "ON" : "OFF"; sw.classList.toggle("on", on); }
    const sel = el.querySelector("select");
    if (sel?.dataset.key === "amp_type") [...sel.options].forEach((o, i) => { o.textContent = ampLabel(i); });
    if (sel) sel.value = get(sel.dataset.key);
    for (const fd of el.querySelectorAll(".fader")) paintFader(fd, get(fd.dataset.fader));
  }

  rememberDraft();
  updateActions(mod);
  scheduleLive();
  scheduleCloud();
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
      c.dataset.slot = s;
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
  $("mInput").hidden = true;
  $("mBody").innerHTML = "";
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
    const dev = await openMidi(store.get("tankg.port", ""));
    const fromDemo = S.demo;
    S.dev = dev;
    S.demo = false;
    S.wanted = true;
    loadAliases();
    watchPorts(dev.access);
    adoptBank(dev.bank, fromDemo);
    toast(`Tank-G conectada (${S.dev.portName})`);
    setTimeout(cloudStartup, 500);
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

async function applyPresets(first, items, bank = "", forceUpload = false) {
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
  if (!(forceUpload || $("libUpload").checked) || !S.dev) {
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
      download(`tankg-${stamp}.tgbank`, fromHex(b.hex));
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

// generic dialogs ---------------------------------------------------------------------------------

function promptText(title, text, value = "") {
  return new Promise(resolve => {
    modal({ title, step: text, ok: "Aceptar", cancel: "Cancelar" });
    const input = $("mInput");
    input.hidden = false;
    input.value = value;
    setTimeout(() => input.focus(), 50);
    $("mOk").onclick = () => { closeModal(); resolve(input.value); };
    $("mClose").onclick = () => { closeModal(); resolve(null); };
  });
}

function showText(title, text) {
  modal({ title });
  $("mBody").innerHTML = "<pre></pre>";
  $("mBody").firstChild.textContent = text;
  $("mClose").onclick = closeModal;
}

/** Choose another slot (duplicate / swap), like the desktop "elige el slot" dialog. */
function pickSlot(title, exclude) {
  return new Promise(resolve => {
    modal({ title, step: "Elige el slot de destino:", cancel: "Cancelar" });
    const grid = document.createElement("div");
    grid.className = "picker";
    for (let b = 0; b < 9; b++) {
      const lab = document.createElement("span");
      lab.textContent = b + 1;
      grid.append(lab);
      for (let i = 0; i < 4; i++) {
        const s = b * 4 + i, btn = document.createElement("button");
        btn.textContent = presetName(s) || slotName(s);
        btn.style.borderColor = rgbHex(S.local.presets[s]);
        btn.disabled = s === exclude;
        btn.onclick = () => { closeModal(); resolve(s); };
        grid.append(btn);
      }
    }
    $("mBody").append(grid);
    $("mClose").onclick = () => { closeModal(); resolve(null); };
  });
}

/** Long press (or right click) on a preset: the same per-preset menu as the desktop. */
function presetMenu(slot) {
  select(slot);
  const mod = modified().includes(slot);
  const acts = [
    ["Activar en la pedalera", "activate", !!S.dev], ["Guardar este preset", "saveOne", mod && !!S.dev],
    ["Revertir este preset", "revert", mod], ["Biblioteca de sonidos", "library", true], ["Crear con IA…", "ai", true],
    ["Copiar", "copy", true], ["Pegar", "paste", !!S.clipboard], ["Duplicar en otro slot…", "duplicate", true],
    ["Intercambiar con otro slot…", "swap", true], ["Renombrar preset", "rename", true],
    ["Exportar preset", "exportPreset", true], ["Restaurar de fábrica", "factory", !!factoryHex()],
  ];
  modal({ title: `${slotName(slot)}${presetName(slot) ? ` · ${presetName(slot)}` : ""}`, cancel: "Cerrar" });
  const box = document.createElement("div");
  box.className = "acts";
  for (const [label, cmd, enabled] of acts) {
    const b = document.createElement("button");
    b.textContent = label;
    b.disabled = !enabled;
    b.onclick = () => { closeModal(); run(cmd); };
    box.append(b);
  }
  $("mBody").append(box);
  $("mClose").onclick = closeModal;
}

// AMP models (.am4data, Bluetooth only; same as the desktop AmpUploadDialog) ---------------------

function pickAmpSlot() {
  return new Promise(resolve => {
    modal({ title: "Espacio de AMP", step: "Elige qué modelo de AMP (perilla TYPE) se reemplaza:", cancel: "Cancelar" });
    const box = document.createElement("div");
    box.className = "acts";
    const current = S.local ? get("amp_type") : -1;
    for (let i = 0; i < AMP_MODELS.length; i++) {
      const b = document.createElement("button");
      b.textContent = ampLabel(i) + (i === current ? "  (preset actual)" : "");
      b.onclick = () => { closeModal(); resolve(i); };
      box.append(b);
    }
    $("mBody").append(box);
    $("mClose").onclick = () => { closeModal(); resolve(null); };
  });
}

async function uploadAmpModel() {
  if (S.busy) return toast("Hay una operación en curso");
  const f = await pickFile(".am4data,application/octet-stream");
  if (!f) return;
  const data = new Uint8Array(await f.arrayBuffer());
  try { am4.check(data); } catch (e) { return info("Subir modelo de AMP", `${f.name}: ${e.message}`); }
  const typed = await promptText("Subir modelo de AMP", "Nombre que mostrará la app:", am4.nameFromPath(f.name));
  if (typed === null) return;
  const slot = await pickAmpSlot();
  if (slot === null) return;
  const name = typed.trim() || `AMP ${slot + 1}`;
  if (!(await ask("Subir modelo de AMP", `Se reemplazará el ${ampLabel(slot)} de la pedalera por «${name}». Todos los presets `
    + "que usan ese TYPE sonarán con el modelo nuevo. Para volver al original: Menú → Restaurar AMP/CAB de fábrica.\n"
    + "¿Continuar?"))) return;
  if (!S.dev) return info("Subir modelo de AMP", "Pedalera no conectada: enciéndela con Bluetooth y espera a que la app se conecte.");
  S.busy = true;
  modal({ title: "Subiendo modelo de AMP", step: "Calculando el bloque LMT del modelo…", bar: true });
  $("mClose").disabled = true;
  const step = (text, cls = "") => { $("mStep").textContent = text; $("mStep").className = cls; };
  try {
    await new Promise(r => setTimeout(r, 50));   // paint the dialog before the computation
    const payload = am4.uploadPayload(data);
    await S.dev.uploadAmp(slot, payload, (n, total, text) => {
      $("mBar").firstElementChild.style.width = `${(n / total) * 100}%`;
      step(text);
    });
    aliases.amps = { ...(aliases.amps || {}), [String(slot + 1)]: name };
    saveAliases();
    $("mBar").firstElementChild.style.width = "100%";
    step(`✓ AMP ${slot + 1} reemplazado por «${name}»`, "ok");
  } catch (e) {
    step(`✗ ${e instanceof DeviceError ? e.message : `Error inesperado: ${e.message}`}`, "bad");
  } finally {
    $("mClose").disabled = false;
    $("mClose").onclick = closeModal;
    S.busy = false;
    render();
  }
}

/** Factory AMP/CAB models of set AM4 or AM3 and, optionally, its 36 presets (desktop FactoryAmpCabDialog). */
async function restoreFactoryAmpCab() {
  if (S.busy) return toast("Hay una operación en curso");
  const choice = await new Promise(resolve => {
    modal({ title: "Restaurar AMP/CAB de fábrica", cancel: "Cancelar",
      step: "Vuelve a escribir los 9 AMP y 8 CAB que trae la pedalera, igual que M-EFCS (borra los modelos subidos; "
        + "unos 40 s por Bluetooth). Con presets se hace antes un backup del banco y se pierden los cambios sin guardar." });
    const box = document.createElement("div");
    box.className = "acts";
    for (const [kind, label] of Object.entries(FACTORY_SETS))
      for (const presets of [true, false]) {
        const b = document.createElement("button");
        b.textContent = `${label}${kind === "am4" ? " (modelos nuevos)" : " (original)"} · ${presets ? "AMP/CAB y 36 presets" : "solo AMP/CAB"}`;
        b.onclick = () => { closeModal(); resolve({ kind, presets }); };
        box.append(b);
      }
    $("mBody").append(box);
    $("mClose").onclick = () => { closeModal(); resolve(null); };
  });
  if (!choice) return;
  const { kind, presets } = choice, label = FACTORY_SETS[kind];
  if (!(await ask("Restaurar de fábrica", `Se reemplazarán los AMP/CAB${presets ? " y los 36 presets" : ""} de la pedalera `
    + `por los de fábrica ${label}.\n¿Continuar?`))) return;
  if (!S.dev) return info("Restaurar de fábrica", "Pedalera no conectada: enciéndela con Bluetooth y espera a que la app se conecte.");
  S.busy = true;
  modal({ title: `Restaurando fábrica ${label}`, step: "Preparando…", bar: true });
  $("mClose").disabled = true;
  const step = (text, cls = "") => { $("mStep").textContent = text; $("mStep").className = cls; };
  try {
    const res = await fetch(`factory/tankG_${kind}_ampCab.bin`);
    if (!res.ok) throw new Error(`faltan los modelos de fábrica ${label}`);
    const image = new Uint8Array(await res.arrayBuffer());
    step("Backup previo del banco…");
    const before = await S.dev.readBank();
    backup(before, "auto");
    await S.dev.restoreAmpCab(image, (n, total, text) => {
      $("mBar").firstElementChild.style.width = `${(n / total) * (presets ? 90 : 100)}%`;
      step(text);
    });
    if (presets) {
      const target = Bank.fromBytes(fromHex(FACTORY[kind]));
      const after = await S.dev.writePresets(target, target.diffSlots(before), (n, t, s) =>
        step(s === null ? "Verificando los presets…" : `Presets de fábrica ${n + 1} de ${t}…`));
      if (S.local) pushUndo();
      S.device = after;
      S.local = after.copy();
    }
    aliases.amps = {};
    saveAliases();
    store.set("tankg.factorySet", kind);
    $("mBar").firstElementChild.style.width = "100%";
    step(`✓ Pedalera restaurada a fábrica ${label}`, "ok");
  } catch (e) {
    step(`✗ ${e instanceof DeviceError ? e.message : `Error inesperado: ${e.message}`}`, "bad");
  } finally {
    $("mClose").disabled = false;
    $("mClose").onclick = closeModal;
    S.busy = false;
    render();
  }
}

// files -------------------------------------------------------------------------------------------

function pickFile(accept) {
  return new Promise(resolve => {
    const input = $("fileIn");
    input.value = "";
    input.accept = accept;
    input.onchange = () => resolve(input.files[0] || null);
    input.click();
  });
}

function download(name, data, mime = "application/octet-stream") {   // saved in Downloads by MainActivity
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
  let bin = "";
  bytes.forEach(b => { bin += String.fromCharCode(b); });
  const where = A.saveFile(name, btoa(bin), mime);
  toast(where ? `Guardado en ${where}` : "No se pudo guardar el archivo");
}

const safeName = t => t.replace(/[\\/:*?"<>|]/g, "-").trim();

async function openBankFile(title) {
  const f = await pickFile(".tgbank,.bin,application/octet-stream");
  if (!f) return null;
  try { return parseBankFile(new Uint8Array(await f.arrayBuffer())); }
  catch (e) { info("Error", `${f.name}: ${e.message}`); return null; }
}

function loadLocalBank(bank, message) {
  pushUndo();
  S.local = bank;
  render();
  toast(message);
}

function diffText(other, title) {
  const lines = S.local.diffSlots(other).map(s => {
    const a = S.local.presets[s], b = other.presets[s], name = presetName(s);
    const changes = [...a].map((v, i) => (v !== b[i] ? `${BYTE_NAMES[i]} ${b[i]}→${v}` : null)).filter(Boolean).join(", ");
    return `${slotName(s)}${name ? ` (${name})` : ""}: ${changes}`;
  });
  return lines.length ? `${title}:\n${lines.join("\n")}` : "Idénticos.";
}

// preset operations (same set as the desktop Editar menu) -----------------------------------------

function swapSlots(a, b) {
  pushUndo();
  const p = S.local.presets;
  [p[a], p[b]] = [p[b], p[a]];
  const na = presetName(a), nb = presetName(b);
  setPresetName(a, nb);
  setPresetName(b, na);
  S.current = b;
  render();
}

/** Factory set ("am4"/"am3") last restored on the pedal; the editor's factory presets follow it. */
const factorySet = () => (FACTORY_SETS[store.get("tankg.factorySet", "am4")] ? store.get("tankg.factorySet", "am4") : "am4");
const factoryHex = (kind = factorySet()) => FACTORY[kind];

function restoreFactory(slots) {
  if (!factoryHex()) return info("Fábrica", "Esta versión no incluye el banco de fábrica.");
  const factory = Bank.fromBytes(fromHex(factoryHex()));
  pushUndo();
  for (const s of slots) S.local.presets[s] = Uint8Array.from(factory.presets[s]);
  render();
  toast("Presets de fábrica cargados en el editor. «Guardar» los pasa a la pedalera.");
}

// live audition: every change of the selected preset is written and selected after a pause --------

let liveTimer = null;
function scheduleLive() {
  if (!S.live || !S.dev) return;
  clearTimeout(liveTimer);
  liveTimer = setTimeout(liveSend, 700);
}

async function liveSend() {
  if (!S.live || !S.dev || !S.local) return;
  if (S.busy) { scheduleLive(); return; }
  const slot = S.current;
  if (!modified().includes(slot)) return;
  S.busy = true;
  try {
    if (!S.backupDone && !S.demo) { backup(await S.dev.readBank(), "auto"); S.backupDone = true; }
    S.device = await S.dev.writePresets(S.local.copy(), [slot]);
    S.dev.selectPreset(slot);
    toast(`${slotName(slot)} actualizado en la pedalera`, 1500);
  } catch (e) {
    toast(`Error: ${e.message}`, 5000);
  } finally {
    S.busy = false;
    render();
  }
}

async function toggleLive() {
  if (!S.live && !(await ask("Escucha en vivo", "Cada cambio se guardará en la memoria de la pedalera y se activará el preset " +
    "para que lo oigas al momento.\nAntes del primer cambio se hace un backup automático.\n\n¿Activar?"))) return;
  S.live = !S.live;
  document.querySelector('[data-cmd="live"]').classList.toggle("on", S.live);
  toast(S.live ? "Escucha en vivo activada" : "Escucha en vivo desactivada");
  if (S.live) scheduleLive(); else clearTimeout(liveTimer);
}

// MIDI port ---------------------------------------------------------------------------------------

async function midiDevices() {
  return [...JSON.parse(A.list()).map(d => d.name), ...androidBluetoothPedals().map(p => `${p.name} (Bluetooth)`)];
}

async function openPorts() {
  const list = $("portList"), chosen = store.get("tankg.port", "");
  list.innerHTML = "";
  let names = [];
  try { names = await midiDevices(); } catch (e) { $("portState").textContent = e.message; }
  for (const name of ["", ...names]) {
    const row = document.createElement("label");
    row.className = "port";
    row.innerHTML = `<input type="radio" name="port"><span></span>`;
    row.querySelector("span").textContent = name || "Automático (recomendado)";
    row.querySelector("input").value = name;
    row.querySelector("input").checked = name === chosen;
    list.append(row);
  }
  if (!names.length) $("portState").textContent = "No se ve ningún dispositivo MIDI conectado.";
  $("portSheet").hidden = false;
}

const chosenPort = () => document.querySelector('#portList input:checked')?.value ?? "";

// calibration wizard ------------------------------------------------------------------------------

let calRef = null;
async function calRead() {
  if (!S.dev) { info("Calibración", "Conecta la pedalera primero."); return null; }
  if (S.busy) { $("calState").textContent = "Hay una operación en curso; espera unos segundos."; return null; }
  S.busy = true;
  try { return await S.dev.readBank(); } catch (e) { info("Error", e.message); return null; } finally { S.busy = false; }
}

function calLog(text) {
  const log = $("calLog");
  if (log.dataset.empty !== "no") { log.textContent = ""; log.dataset.empty = "no"; }
  log.textContent += text + "\n";
  const saved = store.get("tankg.calibration", []);
  saved.push(`[${new Date().toLocaleString()}] ${text}`);
  store.set("tankg.calibration", saved.slice(-200));
}

// AI ----------------------------------------------------------------------------------------------

const aiState = { result: null };
const aiBank = () => $("aiScope").querySelector(".on").dataset.v === "bank";
const aiApiMode = () => $("aiMode").querySelector(".on").dataset.v === "api";
const aiLikes = () => {
  const first = aiBank() ? Math.floor(S.current / 4) * 4 : S.current;
  return [0, 1, 2, 3].map(i => S.local.presets[first + i] || null);
};

function openAI() {
  if (!S.local) return;
  const cfg = store.get("tankg.ai", {});
  if (!$("aiInstrument").options.length) {
    AI.instruments.forEach(t => $("aiInstrument").add(new Option(t, t)));
    Object.keys(AI.webSites).forEach(t => $("aiSite").add(new Option(t, t)));
    Object.entries(AI.providers).forEach(([k, p]) => $("aiProvider").add(new Option(p.label, k)));
    AI.suggestions.forEach(t => {
      const c = document.createElement("button");
      c.textContent = t;
      c.onclick = () => { $("aiText").value = t; };
      $("aiChips").append(c);
    });
  }
  if (cfg.instrument) $("aiInstrument").value = cfg.instrument;
  if (cfg.site) $("aiSite").value = cfg.site;
  $("aiProvider").value = cfg.provider || "claude";
  aiProviderChanged(cfg);
  setSeg("aiMode", cfg.mode === "api" ? "api" : "web");
  setSeg("aiScope", cfg.scope === "bank" ? "bank" : "one");
  aiState.result = null;
  $("aiResult").hidden = $("aiApply").hidden = true;
  $("aiAnswer").value = "";
  aiScopeChanged();
  $("aiSheet").hidden = false;
}

function setSeg(id, v) {
  for (const b of $(id).children) b.classList.toggle("on", b.dataset.v === v);
  if (id === "aiMode") { $("aiWeb").hidden = v !== "web"; $("aiApi").hidden = v !== "api"; }
  if (id === "aiScope") aiScopeChanged();
}

function aiScopeChanged() {
  const bank = aiBank(), b = Math.floor(S.current / 4);
  $("aiTarget").textContent = bank ? `La IA crea 4 presets coherentes (A–D) para el banco ${b + 1} y lo nombra.`
    : `La IA crea un preset para ${slotName(S.current)}.`;
  const up = S.dev ? " y subir" : "";
  $("aiApply").textContent = bank ? `Aplicar${up} al banco ${b + 1}` : `Aplicar${up} a ${slotName(S.current)}`;
}

function aiProviderChanged(cfg = store.get("tankg.ai", {})) {
  const prov = $("aiProvider").value, p = AI.providers[prov];
  $("aiKey").value = (cfg.keys || {})[prov] || "";
  $("aiRemember").checked = !!(cfg.keys || {})[prov];
  $("aiModel").value = cfg.provider === prov && cfg.model ? cfg.model : p.model;
  $("aiUrl").value = cfg.provider === prov && cfg.baseUrl ? cfg.baseUrl : p.url;
  $("aiKey").placeholder = prov === "compatible" ? "(opcional en servidores locales)" : "sk-…";
}

function aiSave() {
  const old = store.get("tankg.ai", {}), prov = $("aiProvider").value, keys = { ...(old.keys || {}) };
  if ($("aiRemember").checked && $("aiKey").value) keys[prov] = $("aiKey").value; else delete keys[prov];
  store.set("tankg.ai", { mode: aiApiMode() ? "api" : "web", scope: aiBank() ? "bank" : "one", site: $("aiSite").value,
    instrument: $("aiInstrument").value, provider: prov, model: $("aiModel").value, baseUrl: $("aiUrl").value, keys });
}

function aiShow(result) {
  aiState.result = result;
  const box = $("aiResult");
  box.innerHTML = "";
  const items = result.items || [result];
  if (result.bankName) { const h = document.createElement("b"); h.textContent = `Banco «${result.bankName}»`; box.append(h); }
  items.forEach((it, i) => {
    const d = document.createElement("div");
    d.className = "res-p";
    d.style.setProperty("--c", rgbHex(it.bytes));
    d.innerHTML = "<b></b><p></p><p class='muted'></p>";
    d.querySelector("b").textContent = (result.items ? `${"ABCD"[i]} · ` : "") + it.name;
    d.querySelectorAll("p")[0].textContent = it.explanation;
    d.querySelectorAll("p")[1].textContent = `${ampName(it.bytes)} · gain ${it.bytes[6]} · ${CAB_MODELS[it.bytes[17]] ?? "?"}`;
    box.append(d);
  });
  box.hidden = false;
  $("aiApply").hidden = false;
  aiScopeChanged();
  $("aiApply").scrollIntoView({ behavior: "smooth", block: "center" });
}

async function aiGenerate() {
  const text = $("aiText").value.trim();
  if (!text) return toast("Describe primero el sonido.");
  aiSave();
  const btn = $("aiGen");
  btn.disabled = true;
  btn.textContent = "Generando…";
  try {
    aiShow(await generateAI({ provider: $("aiProvider").value, key: $("aiKey").value.trim(), model: $("aiModel").value.trim(),
      baseUrl: $("aiUrl").value.trim() }, text, $("aiInstrument").value, aiBank(), aiLikes()));
  } catch (e) {
    info("Crear con IA", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "✨ Generar";
  }
}

function aiCopy() {
  const text = $("aiText").value.trim();
  if (!text) return toast("Describe primero el sonido.");
  aiSave();
  const prompt = webPrompt(text, $("aiInstrument").value, aiBank());
  A.copyText(prompt);
  const site = $("aiSite").value, url = AI.webSites[site];
  const where = A.openChat(AI.chatApps[site]?.android || "", url, prompt);
  toast(where === "shared" ? `Instrucciones enviadas a la app de ${site}: revisa el mensaje y envíalo (también quedaron copiadas)`
    : `Instrucciones copiadas: pégalas en ${where === "app" ? `la app de ${site}` : "el chat"} y envía`, 5000);
}

function aiRead() {
  try { aiShow(aiFromText($("aiAnswer").value, aiBank(), aiLikes())); }
  catch (e) { info("Crear con IA", e.message); }
}

function aiApply() {
  const r = aiState.result;
  if (!r) return;
  $("aiSheet").hidden = true;
  if (r.items) applyPresets(Math.floor(S.current / 4) * 4, r.items.map(it => ({ bytes: it.bytes, name: it.name })), r.bankName, true);
  else applyPresets(S.current, [{ bytes: r.bytes, name: r.name }], "", true);
}

// updates -----------------------------------------------------------------------------------------

const versionTuple = v => String(v).replace(/^v/, "").split(".").map(n => parseInt(n, 10) || 0);
const newer = (a, b) => { const x = versionTuple(a), y = versionTuple(b); for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0); return false; };
const appVersion = () => A.version?.() || VERSION;

async function checkUpdate(manual = false) {
  let rel;
  try {
    const r = await fetch(`https://api.github.com/repos/${RELEASES_REPO}/releases/latest`, { headers: { accept: "application/vnd.github+json" } });
    if (r.status === 404) { if (manual) info("Actualizaciones", `Todavía no hay versiones publicadas. Tienes la ${appVersion()}.`); return; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    rel = await r.json();
  } catch (e) {
    if (manual) info("Actualizaciones", `No se pudo consultar las versiones (${e.message}). ¿Hay internet?`);
    return;
  }
  store.set("tankg.lastUpdateCheck", Date.now());
  const latest = rel.tag_name, current = appVersion();
  if (!newer(latest, current)) { if (manual) info("Actualizaciones", `Tienes la última versión (${current}).`); return; }
  const asset = n => (rel.assets || []).find(a => a.name === n)?.browser_download_url;
  const notes = String(rel.body || "").split("\n## Verificar")[0].slice(0, 900);
  if (asset("TankG-android.apk") && asset("SHA256SUMS")) {
    if (await ask(`Versión ${latest.replace(/^v/, "")} disponible`, `Tienes la ${current}.\n\n${notes}\n\n¿Descargar e instalar ahora?`, "Actualizar")) {
      modal({ title: "Actualizando", step: "Preparando…", bar: false });
      $("mClose").onclick = closeModal;
      A.installUpdate(asset("TankG-android.apk"), asset("SHA256SUMS"));
    }
  } else if (manual) {
    info("Actualizaciones", `Hay una versión ${latest} pero aún no trae la APK.`);
  }
}
globalThis.__updateState = (state, detail) => {
  if ($("modal").hidden) modal({ title: "Actualizando" });
  $("mStep").textContent = detail;
  $("mStep").className = state === "error" ? "bad" : state === "done" ? "ok" : "";
  $("mClose").onclick = closeModal;
};

// cloud (Google Drive): same files as the desktop app ---------------------------------------------

const cloudState = () => store.get("tankg.cloud", {});
const setCloud = v => store.set("tankg.cloud", v);
const drive = () => (cloud.configured() && cloudState().refreshToken ? new cloud.Drive(cloudState().refreshToken) : null);
// The editor is mirrored a moment after every change once the startup sync is done (same as desktop).
const C = { started: false, ready: false, busy: false, timer: 0 };
const cloudStatus = text => { $("cloudStatus").textContent = text; $("cloudStatus").hidden = !text; };
const cloudDoc = () => {
  const bank = S.local || S.device;
  return bank && !S.demo ? cloud.makeDoc(bank, aliases.presets, aliases.banks, aliases.amps) : null;
};

function scheduleCloud(ms = 2500) {
  if (!C.ready || !drive()) return;
  clearTimeout(C.timer);
  C.timer = setTimeout(cloudAutoPush, ms);
}

async function cloudAutoPush() {
  const d = drive(), doc = cloudDoc();
  if (!d || !doc || (await cloud.docKey(doc)) === cloudState().synced) return;
  if (C.busy) return scheduleCloud();
  C.busy = true;
  cloudStatus("☁ Guardando cambios en la nube…");
  try {
    await cloud.push(d, doc);
    setCloud({ ...cloudState(), synced: await cloud.docKey(doc) });
    cloudStatus(`☁ Cambios guardados en la nube ${new Date().toTimeString().slice(0, 5)}`);
    C.busy = false;
    scheduleCloud();   // changes made during the upload
  } catch {
    C.busy = false;
    cloudStatus("☁ Sin conexión con la nube: se reintentará");
    scheduleCloud(60000);
  }
}

/** Once per start (after connecting the pedal, or a few seconds without it): the editor takes the cloud
 *  version; it only asks when something was edited here before the sync finished. */
async function cloudStartup() {
  if (C.started || S.demo) return;
  C.started = true;
  const d = drive();
  if (!d) return;
  cloudStatus("☁ Sincronizando con la nube…");
  const edits = S.undo.length;
  let doc;
  try { doc = await cloud.pull(d); } catch { C.ready = true; return cloudStatus("☁ Sin conexión con la nube"); }
  C.ready = true;
  const current = cloudDoc(), key = doc && await cloud.docKey(doc);
  if (!doc || (current && (await cloud.docKey(current)) === key)) {
    if (doc) setCloud({ ...cloudState(), synced: key });
    cloudStatus("☁ Al día con la nube");
    return scheduleCloud();   // first device: the cloud starts with this setup
  }
  if (!current || S.undo.length === edits || await ask("Nube", `Hay presets en la nube guardados desde ${doc.device || "otro equipo"} `
    + `(${cloud.when(doc.updated)}) y aquí ya hiciste cambios.\n¿Cargar los de la nube? (si no, la nube se actualiza con lo de este equipo)`)) {
    loadCloud(cloud.parseDoc(doc));
    setCloud({ ...cloudState(), synced: key });
    cloudStatus(`☁ Sincronizado con la nube (${doc.device || "otro equipo"})`);
  }
  scheduleCloud();
}

async function cloudConnect() {
  if (!cloud.configured()) return info("Nube", "Esta versión no tiene configurada la sincronización con Google Drive.");
  let code;
  try { code = await cloud.startSignIn(); } catch (e) { return info("Nube", e.message); }
  let cancelled = false;
  // The code can be entered on any device: opening the browser here is optional (some tablets cut the
  // network of an app in the background while the browser is in front).
  modal({ title: "Conectar con Google Drive", step: `Código: ${code.userCode}\n\n1. En cualquier dispositivo (el PC, otro teléfono o este) `
    + `abre ${code.url.replace("https://", "")} y escribe el código (ya está copiado)\n2. Elige tu cuenta y pulsa «Permitir»\n\n`
    + "Esta ventana se cerrará sola.", ok: "Abrir Google aquí", cancel: "Cancelar" });
  A.copyText(code.userCode);
  $("mOk").onclick = () => A.openUrl(code.url);
  $("mClose").onclick = () => { cancelled = true; closeModal(); };
  try {
    const token = await cloud.finishSignIn(code, () => cancelled);
    setCloud({ refreshToken: token });
    closeModal();
    toast("Conectado con Google Drive: los presets se sincronizan solos", 4000);
    C.started = C.ready = false;
    cloudStartup();
  } catch (e) {
    if (!cancelled) { $("mStep").textContent = e.message; $("mStep").className = "bad"; $("mOk").hidden = true; }
  }
}

async function cloudPush(quiet = true) {
  const d = drive();
  if (!d) { if (!quiet) cloudConnect(); return; }
  const doc = cloudDoc();
  if (!doc) return;
  try {
    await cloud.push(d, doc);
    setCloud({ ...cloudState(), synced: await cloud.docKey(doc) });
    toast("Sincronizado con Google Drive", 1800);
  } catch (e) { quiet ? toast(`Nube: ${e.message}`, 5000) : info("Nube", e.message); }
}

function loadCloud(r) {
  if (S.local) pushUndo();
  S.local = r.bank;
  aliases = { ...aliases, presets: r.presets, banks: r.banks, amps: r.amps || {} };
  saveAliases();
  render();
  const n = modified().length;
  toast(`Presets de la nube cargados${n ? `: ${n} distintos de la pedalera, «Guardar» los pasa` : ""}.`, 4500);
}

async function cloudCheck({ manual = false, afterConnect = false } = {}) {
  const d = drive();
  if (!d || !S.local || S.demo) { if (manual && !d) cloudConnect(); return; }
  let doc;
  try { doc = await cloud.pull(d); } catch (e) { return manual ? info("Nube", e.message) : toast(`Nube: ${e.message}`, 5000); }
  if (!doc) { if (afterConnect || manual) cloudPush(!manual); return; }
  const r = cloud.parseDoc(doc), key = await cloud.docKey(doc);
  const same = key === (await cloud.docKey(cloudDoc()));
  if (same) { setCloud({ ...cloudState(), synced: key }); if (manual) info("Nube", "La nube y este equipo ya tienen lo mismo."); return; }
  if (!manual && key === cloudState().synced) return;
  if (await ask("Nube", `Hay presets en la nube guardados desde ${doc.device || "otro equipo"} (${cloud.when(doc.updated)}).\n` +
    "¿Cargarlos en el editor? La pedalera no cambia hasta que pulses «Guardar».")) loadCloud(r);
  setCloud({ ...cloudState(), synced: key });
}

async function cloudHistory() {
  const d = drive();
  if (!d) return cloudConnect();
  let files;
  try { files = await cloud.history(d); } catch (e) { return info("Nube", e.message); }
  if (!files.length) return info("Nube", "Todavía no hay nada guardado en la nube.");
  modal({ title: "Historial de la nube", step: "Versión para cargar en el editor:", cancel: "Cerrar" });
  const box = document.createElement("div");
  box.className = "acts";
  for (const f of files) {
    const b = document.createElement("button");
    b.textContent = (f.name === cloud.LATEST ? "Última · " : "") + cloud.when(f.modifiedTime);
    b.onclick = async () => {
      closeModal();
      try { loadCloud(cloud.parseDoc(await d.read(f.id))); } catch (e) { info("Nube", e.message); }
    };
    box.append(b);
  }
  $("mBody").append(box);
  $("mClose").onclick = closeModal;
}

// command dispatcher: menu sheet, preset long-press menu and toolbar share it --------------------

async function run(cmd) {
  $("menuSheet").hidden = true;
  const needLocal = !["read", "demo", "about", "view", "port", "ampUpload", "factoryAmpCab", "update", "calibrate", "backups", "cloudConnect", "cloudDisconnect"].includes(cmd);
  if (needLocal && !S.local) return info("Sin datos", "Conecta la pedalera o abre un archivo de banco.");
  const cur = S.current, bankFirst = Math.floor(cur / 4) * 4;
  switch (cmd) {
    case "read": return readDevice();
    case "saveAll": return saveAll();
    case "saveOne": return modified().includes(cur) ? upload([cur], cur) : toast(`${slotName(cur)} no tiene cambios: ya está en la pedalera.`);
    case "activate":
      if (!S.dev) return toast("Pedalera no conectada");
      S.dev.selectPreset(cur);
      return toast(`${slotName(cur)} activo en la pedalera`);
    case "live": return toggleLive();
    case "backupNow":
      if (!S.dev) return toast("Pedalera no conectada");
      if (S.busy) return toast("Hay una operación en curso");
      S.busy = true;
      try { backup(await S.dev.readBank(), "manual"); toast("Backup guardado (Menú → Gestor de backups)"); }
      catch (e) { info("Error", e.message); } finally { S.busy = false; }
      return;
    case "backups": return openBackups();
    case "restoreFile": {
      if (!S.device) return info("Restaurar", "Conecta la pedalera primero.");
      const bank = await openBankFile();
      if (!bank) return;
      pushUndo();
      S.local = bank;
      render();
      return saveAll();
    }
    case "port": return openPorts();
    case "ampUpload": return uploadAmpModel();
    case "factoryAmpCab": return restoreFactoryAmpCab();
    case "calibrate": $("calSheet").hidden = false; return;
    case "undo": return $("undo").click();
    case "copy": S.clipboard = Uint8Array.from(S.local.presets[cur]); return toast(`Preset ${slotName(cur)} copiado`);
    case "paste":
      if (!S.clipboard) return toast("Primero copia un preset");
      pushUndo(); S.local.presets[cur] = Uint8Array.from(S.clipboard); return render();
    case "duplicate": {
      const d = await pickSlot("Duplicar preset", cur);
      if (d === null) return;
      pushUndo();
      S.local.presets[d] = Uint8Array.from(S.local.presets[cur]);
      if (presetName(cur)) setPresetName(d, presetName(cur));
      S.current = d;
      return render();
    }
    case "swap": { const d = await pickSlot("Intercambiar preset", cur); if (d !== null) swapSlots(cur, d); return; }
    case "left": if (cur > 0) swapSlots(cur, cur - 1); return;
    case "right": if (cur < SLOTS - 1) swapSlots(cur, cur + 1); return;
    case "rename": $("alias").focus(); $("alias").select(); return;
    case "renameBank": {
      const b = Math.floor(cur / 4), v = await promptText(`Nombre del banco ${b + 1}`, "Solo en esta app: la pedalera no guarda nombres.", bankName(b));
      if (v === null) return;
      pushUndo();
      const name = v.trim();
      if (name) aliases.banks[String(b + 1)] = name; else delete aliases.banks[String(b + 1)];
      saveAliases();
      return render();
    }
    case "library": return openLibrary();
    case "ai": return openAI();
    case "factory": return restoreFactory([cur]);
    case "factoryBank": return restoreFactory([0, 1, 2, 3].map(i => bankFirst + i));
    case "factoryAll":
      if (await ask("Fábrica", "¿Cargar en el editor los 36 presets de fábrica?\nLa pedalera no cambia hasta que pulses «Guardar».")) restoreFactory([...Array(SLOTS).keys()]);
      return;
    case "revert": if (S.device) { pushUndo(); S.local.presets[cur] = Uint8Array.from(S.device.presets[cur]); render(); } return;
    case "revertAll": if (S.device) { pushUndo(); S.local = S.device.copy(); render(); } return;
    case "openBank": { const b = await openBankFile(); if (b) loadLocalBank(b, "Banco abierto. «Guardar» lo pasa a la pedalera."); return; }
    case "saveBank": return download(`tankg-${stamp()}.tgbank`, S.local.toBytes());
    case "importPreset": {
      const f = await pickFile(".tgpreset,application/json");
      if (!f) return;
      try {
        const { record, name } = parsePresetFile(await f.text());
        pushUndo();
        S.local.presets[cur] = record;
        if (name) setPresetName(cur, name);
        return render();
      } catch (e) { return info("Error", `${f.name}: ${e.message}`); }
    }
    case "exportPreset": {
      const name = presetName(cur);
      return download(safeName(`${slotName(cur)} ${name}`) + ".tgpreset", presetFile(S.local.presets[cur], cur, name), "application/json");
    }
    case "importSet": {
      const f = await pickFile(".tgset,application/json");
      if (!f) return;
      let set;
      try { set = parseSetFile(await f.text()); } catch (e) { return info("Error", `${f.name}: ${e.message}`); }
      const items = set.items.slice(0, 4), b = Math.floor(cur / 4);
      if (!(await ask("Importar banco", `¿Reemplazar los presets ${b + 1}A–${b + 1}${"ABCD"[items.length - 1]} del editor con «${set.title || f.name}»?`))) return;
      pushUndo();
      items.forEach((it, i) => { S.local.presets[b * 4 + i] = it.record; setPresetName(b * 4 + i, it.name || ""); });
      if (set.title) { aliases.banks[String(b + 1)] = set.title; saveAliases(); }
      return render();
    }
    case "exportSet": {
      const b = Math.floor(cur / 4), title = bankName(b) || `Banco ${b + 1}`, slots = [0, 1, 2, 3].map(i => b * 4 + i);
      return download(safeName(title) + ".tgset", setFile(S.local, slots, slots.map(presetName), title), "application/json");
    }
    case "compare": { const other = await openBankFile(); if (other) showText("Comparación", diffText(other, "Archivo → editor")); return; }
    case "bytes": {
      const hexs = b => [...b].map(v => v.toString(16).padStart(2, "0")).join(" ");
      return showText(`Bytes de ${slotName(cur)}`, `Local:     ${hexs(S.local.presets[cur])}\nPedalera: ${S.device ? hexs(S.device.presets[cur]) : "—"}\n\n` +
        [...S.local.presets[cur]].map((v, i) => `${String(i).padStart(2)}  ${BYTE_NAMES[i].padEnd(11)} ${v}`).join("\n"));
    }
    case "view":
      view = { auto: "phone", phone: "tablet", tablet: "auto" }[view];
      store.set("tankg.view", view);
      applyView();
      return toast(`Vista ${VIEWS[view]}`);
    case "demo": return startDemo();
    case "update": return checkUpdate(true);
    case "cloudConnect": return cloudConnect();
    case "cloudPush": return cloudPush(false);
    case "cloudPull": return cloudCheck({ manual: true });
    case "cloudHistory": return cloudHistory();
    case "cloudDisconnect":
      if (cloudState().refreshToken && await ask("Nube", "¿Desconectar de Google Drive en este equipo?\nLo guardado en la nube no se borra.")) {
        cloudStatus("");
        setCloud({});
        toast("Desconectado de Google Drive");
      }
      return;
    case "about":
      info("Tank-G Control Center", `Versión ${appVersion()}\n\nEditor de presets para la M-VAVE Tank-G: la misma app en ` +
        "Windows, Linux y Android, con el protocolo verificado, backup antes de escribir y verificación por relectura.\n\n" +
        "Conecta la pedalera por USB-OTG o emparéjala por Bluetooth (Tank-G v2).");
      $("mBody").innerHTML = "";
      for (const [text, url] of [["Política de privacidad", LEGAL.privacy], ["Condiciones del servicio", LEGAL.terms]]) {
        const b = document.createElement("button");
        b.className = "link";
        b.textContent = text;
        b.onclick = () => A.openUrl(url);
        $("mBody").append(b);
      }
      return;
  }
}

// wiring ------------------------------------------------------------------------------------

function wire() {
  $("connect").onclick = $("connectBig").onclick = () => connect();
  $("demoBig").onclick = startDemo;
  $("menuBtn").onclick = () => { document.querySelector('[data-cmd="live"]').classList.toggle("on", S.live); $("menuSheet").hidden = false; };
  $("menuSheet").onclick = e => { const cmd = e.target.closest("[data-cmd]")?.dataset.cmd; if (cmd) run(cmd); };
  $("bankTag").onclick = () => run("renameBank");
  // long press on a footswitch or a preset of the list: per-preset menu (desktop right click)
  document.addEventListener("contextmenu", e => {
    const foot = e.target.closest(".foot"), slot = e.target.closest(".bslot");
    if (!foot && !slot || !S.local) return;
    e.preventDefault();
    presetMenu(foot ? Math.floor(S.current / 4) * 4 + +foot.dataset.i : +slot.dataset.slot);
  });
  for (const id of ["aiScope", "aiMode"]) $(id).onclick = e => { if (e.target.dataset.v) setSeg(id, e.target.dataset.v); };
  $("aiProvider").onchange = () => aiProviderChanged();
  $("aiGen").onclick = aiGenerate;
  $("aiCopy").onclick = aiCopy;
  $("aiRead").onclick = aiRead;
  $("aiApply").onclick = aiApply;
  $("calRef").onclick = async () => {
    const b = await calRead();
    if (!b) return;
    calRef = b;
    $("calRead").disabled = false;
    $("calState").textContent = `Referencia tomada a las ${new Date().toLocaleTimeString()}.`;
    calLog("Referencia tomada. Ahora guarda desde la pedalera.");
  };
  $("calRead").onclick = async () => {
    const b = await calRead();
    if (!b || !calRef) return;
    const lines = [];
    for (const s of b.diffSlots(calRef))
      for (let i = 0; i < 21; i++)
        if (calRef.presets[s][i] !== b.presets[s][i])
          lines.push(`  ${slotName(s)}  byte ${String(i).padStart(2)}  ${BYTE_NAMES[i].padEnd(11)} ${String(calRef.presets[s][i]).padStart(3)} → ${String(b.presets[s][i]).padStart(3)}`);
    calLog(lines.length ? "Cambios:\n" + lines.join("\n") : "Sin cambios: ¿guardaste en la pedalera?");
    calRef = b;
  };
  $("portTest").onclick = async () => {
    $("portState").textContent = "Probando…";
    if (S.busy) { $("portState").textContent = "Hay una operación en curso."; return; }
    S.busy = true;
    const port = chosenPort();
    if (S.dev && !S.demo && (port === "" || port === S.dev.portName)) {   // already talking to it: don't cut the link
      S.busy = false;
      $("portState").textContent = `✓ Tank-G conectada en «${S.dev.portName}».`;
      return;
    }
    try {
      const dev = await openMidi(port);   // on Android this replaces the open device
      $("portState").textContent = `✓ Tank-G encontrada en «${dev.portName}».`;
      const fromDemo = S.demo;
      S.dev = dev;
      S.demo = false;
      watchPorts(dev.access);
      adoptBank(dev.bank, fromDemo);
      render();
    } catch (e) {
      $("portState").textContent = `✗ ${e.message}`;
      if (S.dev && !S.demo) { S.dev = null; render(); }   // the old link was closed by the attempt
    } finally { S.busy = false; }
  };
  $("portSave").onclick = () => {
    store.set("tankg.port", chosenPort());
    $("portSheet").hidden = true;
    S.dev?.t?.close?.();
    S.dev = null;
    render();
    connect();
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
    aliases = { ...JSON.parse(u.aliases), amps: aliases.amps };   // the AMP models live in the pedal, not in the undo history
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
// Connect now and whenever the pedal is plugged in; Bluetooth pedals are retried while the app is open.
$("emptyHint").textContent = "Conecta la pedalera por USB-OTG o, si es una Tank-G v2, emparéjala por Bluetooth en los ajustes de Android: se conecta sola.";
S.wanted = true;
midiAccess().then(watchPorts);
connect(true);
setTimeout(cloudStartup, 4000);   // without a pedal: sync the editor anyway
setInterval(() => {   // a Bluetooth pedal sends no "plugged in" event: retry quietly, like M-EFCS
  if (S.wanted && !S.dev && !S.busy && !S.demo && document.visibilityState === "visible" && androidBluetoothPedals().length) connect(true);
}, 15000);

if (Date.now() - store.get("tankg.lastUpdateCheck", 0) > 20 * 3600 * 1000) setTimeout(() => checkUpdate(false), 4000);

window.tankg = { S, connect, startDemo, upload, applyPresets, run, checkUpdate };   // for debugging over adb

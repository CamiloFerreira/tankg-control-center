// Tank-G protocol for the browser: a 1:1 port of tankg/sysex.py, tankg/model.py and the
// TankG class of tankg/device.py. Same frames, same verified operations (research/FINDINGS.md):
//   read bank     space 0, field 0, len 758
//   write preset  CLS 09, CMD 0x41 + 8*21, space 0, field 2 + 21*slot, then ACK
//   commit        CLS 09, CMD 0x41, space F, len 0, then ACK
//   select        MIDI Program Change 0..35 on channel 1

export const SLOTS = 36, REC_LEN = 21, BANK_LEN = 2 + SLOTS * REC_LEN;   // 758
export const CLS_ACK = 0x01, CLS_WRITE = 0x09, CLS_READ = 0x0d, CMD_READ = 0x41;
export const SPACE_BANK = 0x0, SPACE_COMMIT = 0xf;
export const ACK = Uint8Array.from([0xf0, 0x00, 0x32, 0x01, 0x08, 0x00, 0x00, 0x00, 0x00, 0x7f, 0x01, 0xf7]);
const HEADER_LEN = 14;

export class DeviceError extends Error {}

// sysex codec --------------------------------------------------------------------------

export function pack7(data) {
  const out = [];
  let acc = 0, nbits = 0;
  for (const b of data) {
    acc |= b << nbits;
    nbits += 8;
    while (nbits >= 7) { out.push(acc & 0x7f); acc >>>= 7; nbits -= 7; }
  }
  if (nbits) out.push(acc & 0x7f);
  return out;
}

export function unpack7(data) {
  const out = [];
  let acc = 0, nbits = 0;
  for (const b of data) {
    acc |= (b & 0x7f) << nbits;
    nbits += 7;
    while (nbits >= 8) { out.push(acc & 0xff); acc >>>= 8; nbits -= 8; }
  }
  return out;
}

const u32To7 = v => [v & 0x7f, (v >>> 7) & 0x7f, (v >>> 14) & 0x7f, (v >>> 21) & 0x7f];
const u32From7 = b => b[0] | b[1] << 7 | b[2] << 14 | b[3] << 21;
const leSum = v => (v & 0xff) + ((v >>> 8) & 0xff) + ((v >>> 16) & 0xff) + ((v >>> 24) & 0xff);

export function checksum(field, length, space, payload) {
  let total = leSum(field) + leSum((length << 8) | (space << 4));
  for (const b of payload) total += b;
  return (0xfb - total) & 0xff;
}

export function build(cls, cmd, field, length, space, payload = []) {
  const ck = checksum(field, length, space, payload);
  return Uint8Array.from([0xf0, 0x00, 0x32, cls, ...u32To7(cmd), 0x02, ...u32To7(field),
    ...u32To7((length << 4) | space), ...pack7([...payload, ck]), 0xf7]);
}

export function parse(frame) {
  if (frame[0] !== 0xf0 || frame[1] !== 0x00 || frame[2] !== 0x32 || frame[frame.length - 1] !== 0xf7)
    throw new Error("not an M-VAVE frame");
  const body = frame.slice(3, -1);
  if (body.length < HEADER_LEN) throw new Error("short frame");
  const hdr = body.slice(0, HEADER_LEN);
  const sub = u32From7(hdr.slice(10, 14));
  const length = sub >>> 4, space = sub & 0xf, field = u32From7(hdr.slice(6, 10));
  const dec = unpack7(body.slice(HEADER_LEN));
  const payload = dec.slice(0, -1), ck = dec.length ? dec[dec.length - 1] : null;
  if (ck !== null && ck !== checksum(field, length, space, payload)) throw new Error("bad checksum");
  return { cls: hdr[0], cmd: u32From7(hdr.slice(1, 5)), field, length, space, payload: Uint8Array.from(payload) };
}

export const readFrame = (field, length, space) => build(CLS_READ, CMD_READ, field, length, space);
export const COMMIT_FRAME = build(CLS_WRITE, CMD_READ, 0, 0, SPACE_COMMIT);
export const recordOffset = slot => 2 + REC_LEN * slot;
export const slotName = slot => `${Math.floor(slot / 4) + 1}${"ABCD"[slot % 4]}`;
const sameBytes = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
export const toHex = b => Array.from(b, v => v.toString(16).padStart(2, "0")).join("");
export const fromHex = h => Uint8Array.from(h.match(/../g).map(x => parseInt(x, 16)));

// bank model -------------------------------------------------------------------------------

export class Bank {
  constructor(presets) { this.presets = presets; }   // 36 x Uint8Array(21)

  static fromBytes(data) {
    if (data.length !== BANK_LEN) throw new Error(`el banco debe tener ${BANK_LEN} bytes (tiene ${data.length})`);
    if (data[0] !== 0xa5 || data[1] !== 0x5a) throw new Error("firma de banco incorrecta (se esperaba A5 5A)");
    return new Bank(Array.from({ length: SLOTS }, (_, i) => data.slice(recordOffset(i), recordOffset(i + 1))));
  }

  toBytes() {
    const out = new Uint8Array(BANK_LEN);
    out[0] = 0xa5; out[1] = 0x5a;
    this.presets.forEach((p, i) => out.set(p, recordOffset(i)));
    return out;
  }

  copy() { return new Bank(this.presets.map(p => Uint8Array.from(p))); }
  diffSlots(other) { return this.presets.map((p, i) => i).filter(i => !sameBytes(this.presets[i], other.presets[i])); }
}

// device -------------------------------------------------------------------------------------

/** Talks to the pedal through a transport: { send(Uint8Array), onMessage(cb), close() }. */
export class TankG {
  constructor(transport) {
    this.t = transport;
    this.waiters = [];
    transport.onMessage(msg => {
      for (const w of [...this.waiters]) {
        const r = w.accept(msg);
        if (r !== undefined && r !== null) { this.waiters.splice(this.waiters.indexOf(w), 1); w.resolve(r); }
      }
    });
  }

  transact(frame, accept, timeout = 2000) {
    return new Promise(resolve => {
      const w = { accept, resolve };
      this.waiters.push(w);
      setTimeout(() => { const i = this.waiters.indexOf(w); if (i >= 0) { this.waiters.splice(i, 1); resolve(null); } }, timeout);
      this.t.send(frame);
    });
  }

  async readBank(retries = 3) {
    const frame = readFrame(0, BANK_LEN, SPACE_BANK);
    const accept = msg => {
      try {
        const f = parse(msg);
        return f.cls === CLS_READ && f.length === BANK_LEN && f.payload.length === BANK_LEN ? f.payload : null;
      } catch { return null; }
    };
    for (let i = 0; i < retries; i++) {
      const payload = await this.transact(frame, accept);
      if (payload) {
        try { return Bank.fromBytes(payload); }
        catch (e) { throw new DeviceError(`El dispositivo respondió pero no parece una Tank-G: ${e.message}`); }
      }
      await new Promise(r => setTimeout(r, 300));
    }
    throw new DeviceError("No se pudo leer el banco de presets (sin respuesta).");
  }

  async expectAck(frame, what) {
    const ok = await this.transact(frame, m => (sameBytes(m, ACK) ? true : null), 3000);
    if (!ok) throw new DeviceError(`La pedalera no confirmó: ${what}`);
  }

  async writePreset(slot, record) {
    if (!(slot >= 0 && slot < SLOTS)) throw new Error("slot out of range");
    const frame = build(CLS_WRITE, CMD_READ + 8 * REC_LEN, recordOffset(slot), REC_LEN, SPACE_BANK, record);
    await this.expectAck(frame, `escritura del preset ${slotName(slot)}`);
    await this.expectAck(COMMIT_FRAME, "commit");
  }

  selectPreset(slot) {
    if (!(slot >= 0 && slot < SLOTS)) throw new Error("slot out of range");
    this.t.send(Uint8Array.from([0xc0, slot]));
  }

  /** Write the slots, then read back and verify. progress(n, total, slot|null). */
  async writePresets(target, slots, progress) {
    for (let n = 0; n < slots.length; n++) {
      progress?.(n, slots.length, slots[n]);
      await this.writePreset(slots[n], target.presets[slots[n]]);
    }
    progress?.(slots.length, slots.length, null);
    const after = await this.readBank();
    const bad = slots.filter(s => !sameBytes(after.presets[s], target.presets[s]));
    if (bad.length) throw new DeviceError(`Verificación fallida en ${bad.map(slotName).join(", ")}: la pedalera no guardó lo enviado.`);
    return after;
  }
}

// Bluetooth LE ----------------------------------------------------------------------------------
// The official app talks to the Tank-G v2 over the Jieli serial service (write ae41, notify ae42)
// with its own framing; captured on 2026-10-27 (research/FINDINGS.md):
//   00 59 | cmd | len u16 LE | 00 | f1 u32 LE | f2 u32 LE | data | ck      ck = 0xFF - Σ(f1,f2,data)
//   f1 = addr << 8 | 4        f2 = len << 8 | space << 4        (same memory map as USB)
//   cmd 23 read  -> reply cmd 23 with f1 f2 echoed + data;  cmd 22 write -> ACK 00 59 00 01 00 00 00 ff
//   space 0 = bank (addr 2 + 21*slot), F = commit (len 0), E = select preset (addr = slot, data 01)
export const BLE_SERVICE = "0000ae40-0000-1000-8000-00805f9b34fb";
export const BLE_TX = "0000ae41-0000-1000-8000-00805f9b34fb";
export const BLE_RX = "0000ae42-0000-1000-8000-00805f9b34fb";
const BLE_READ = 0x23, BLE_WRITE = 0x22, BLE_CHUNK = 200;
const le32 = v => [v & 0xff, (v >>> 8) & 0xff, (v >>> 16) & 0xff, (v >>> 24) & 0xff];

export function bleFrame(cmd, space, addr, len, data = []) {
  const payload = [...le32((addr << 8) | 4), ...le32((len << 8) | (space << 4)), ...data];
  const ck = (0xff - payload.reduce((a, b) => a + b, 0)) & 0xff;
  return Uint8Array.from([0x00, 0x59, cmd, payload.length & 0xff, payload.length >> 8, 0x00, ...payload, ck]);
}

/** Splits the notification stream into frames (a reply can span several notifications). */
export class BleDeframer {
  constructor() { this.buf = []; }
  push(bytes) {
    this.buf.push(...bytes);
    const out = [];
    for (;;) {
      const start = this.buf.findIndex((b, i) => b === 0x00 && this.buf[i + 1] === 0x59);
      if (start < 0) { this.buf = this.buf.slice(-1); return out; }
      if (start > 0) this.buf = this.buf.slice(start);
      if (this.buf.length < 6) return out;
      const total = 6 + (this.buf[3] | (this.buf[4] << 8)) + 1;
      if (this.buf.length < total) return out;
      const f = this.buf.slice(0, total);
      this.buf = this.buf.slice(total);
      const payload = f.slice(6, -1);
      if (((0xff - payload.reduce((a, b) => a + b, 0)) & 0xff) === f[total - 1]) out.push({ cmd: f[2], payload });
    }
  }
}

/** Same interface as TankG (readBank, writePresets, selectPreset) over the Bluetooth framing. */
export class TankGBle {
  constructor(transport) {
    this.t = transport;
    this.waiters = [];
    const deframer = new BleDeframer();
    transport.onMessage(bytes => {
      for (const f of deframer.push(bytes))
        for (const w of [...this.waiters]) {
          const r = w.accept(f);
          if (r !== undefined && r !== null) { this.waiters.splice(this.waiters.indexOf(w), 1); w.resolve(r); }
        }
    });
  }

  transact(frame, accept, timeout = 3000) {
    return new Promise(resolve => {
      const w = { accept, resolve };
      this.waiters.push(w);
      setTimeout(() => { const i = this.waiters.indexOf(w); if (i >= 0) { this.waiters.splice(i, 1); resolve(null); } }, timeout);
      if (!this.t.send(frame)) { this.waiters.splice(this.waiters.indexOf(w), 1); resolve(null); }
    });
  }

  async read(space, addr, len, retries = 3) {   // a radio link drops a reply now and then: retry like USB
    const frame = bleFrame(BLE_READ, space, addr, len);
    const echo = Array.from(frame.slice(6, 14));
    for (let i = 0; i < retries; i++) {
      const data = await this.transact(frame, f => (f.cmd === BLE_READ && f.payload.length === 8 + len &&
        echo.every((b, j) => f.payload[j] === b) ? f.payload.slice(8) : null), 1500);
      if (data) return data;
    }
    throw new DeviceError("La pedalera no respondió por Bluetooth.");
  }

  async write(space, addr, data, what) {
    const ok = await this.transact(bleFrame(BLE_WRITE, space, addr, data.length, data),
      f => (f.cmd === 0x00 && f.payload.length === 1 && f.payload[0] === 0x00 ? true : null));
    if (!ok) throw new DeviceError(`La pedalera no confirmó: ${what}`);
  }

  async readBank() {
    const bytes = [];
    for (let addr = 0; addr < BANK_LEN; addr += BLE_CHUNK) bytes.push(...(await this.read(0, addr, Math.min(BLE_CHUNK, BANK_LEN - addr))));
    try { return Bank.fromBytes(Uint8Array.from(bytes)); }
    catch (e) { throw new DeviceError(`El dispositivo respondió pero no parece una Tank-G: ${e.message}`); }
  }

  async writePreset(slot, record) {
    if (!(slot >= 0 && slot < SLOTS)) throw new Error("slot out of range");
    await this.write(0, recordOffset(slot), Array.from(record), `escritura del preset ${slotName(slot)}`);
    await this.write(SPACE_COMMIT, 0, [], "commit");
  }

  selectPreset(slot) {
    if (!(slot >= 0 && slot < SLOTS)) throw new Error("slot out of range");
    this.t.send(bleFrame(BLE_WRITE, 0xe, slot, 1, [1]));
  }

  writePresets(target, slots, progress) { return TankG.prototype.writePresets.call(this, target, slots, progress); }
}

// transports -------------------------------------------------------------------------------

const PORT_HINTS = ["usb composite device", "tank", "m-vave", "mvave", "jieli"];
const WEAK_HINTS = ["usb-midi", "usb midi"];
const score = name => {
  const n = (name || "").toLowerCase();
  return PORT_HINTS.some(h => n.includes(h)) ? 2 : WEAK_HINTS.some(h => n.includes(h)) ? 1 : 0;
};

/** Opens the pedal through the APK's native bridge: USB-MIDI first, then bonded Bluetooth pedals. */
export const openMidi = (port = "") => openAndroidMidi(port);

/** A port chosen by the user wins (like the desktop "Puerto MIDI…" setting); otherwise best match first. */
function choose(items, port) {
  if (!port) return [...items].sort((a, b) => score(b.name) - score(a.name));
  const hit = items.filter(d => d.name === port);
  if (!hit.length) throw new DeviceError(`El puerto elegido «${port}» no está conectado. Elige otro en Menú → Puerto MIDI…`);
  return hit;
}

/** Object whose onstatechange({port: {state, name}}) fires when MIDI devices come and go. */
export const midiAccess = () => Promise.resolve(androidAccess);

// MainActivity exposes `AndroidMidi` (android.media.midi + Bluetooth LE) and calls back into
// these globals with hex strings; complete SysEx frames only.
const androidAccess = { onstatechange: null };
let androidIn = null;
const androidOpens = new Map();
globalThis.__midiIn = hex => androidIn?.(fromHex(hex));
globalThis.__midiState = (state, name) => androidAccess.onstatechange?.({ port: { state, name } });
globalThis.__midiOpened = (id, ok, error) => { androidOpens.get(id)?.(ok ? null : error || "error"); androidOpens.delete(id); };

function androidOpen(id) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { androidOpens.delete(id); reject(new DeviceError("La pedalera no respondió al abrirla.")); }, 5000);
    androidOpens.set(id, err => { clearTimeout(timer); err ? reject(new DeviceError(`No se pudo abrir el dispositivo MIDI: ${err}`)) : resolve(); });
    globalThis.AndroidMidi.open(id);
  });
}

const bleWaiters = [];
let bleIn = null;
globalThis.__bleIn = hex => bleIn?.(fromHex(hex));
globalThis.__bleState = (state, detail) => {
  for (const w of bleWaiters.splice(0)) w(state, detail);
  if (state === "disconnected") androidAccess.onstatechange?.({ port: { state: "disconnected", name: androidBleName } });
};
let androidBleName = "";

/** Bluetooth pedals bonded in Android's settings (the APK asks for the permission). */
export function androidBluetoothPedals() {
  const A = globalThis.AndroidMidi;
  if (!A?.blePedals || !A.blePermission()) return [];
  return JSON.parse(A.blePedals());
}

let bleOpening = null;
/** One Bluetooth connection attempt at a time: a second open would close the first link. */
function openAndroidBle(pedal) {
  if (!bleOpening) bleOpening = connectAndroidBle(pedal).finally(() => { bleOpening = null; });
  return bleOpening;
}

async function connectAndroidBle(pedal) {
  const A = globalThis.AndroidMidi;
  const state = await new Promise(resolve => {
    bleWaiters.push(resolve);
    A.bleOpen(pedal.address);
    setTimeout(() => resolve("error", "tiempo agotado"), 12000);
  });
  if (state !== "ready") { A.bleClose(); throw new DeviceError(`No se pudo conectar por Bluetooth con ${pedal.name}.`); }
  const dev = new TankGBle({
    send: data => A.bleSend(toHex(data)),
    onMessage: f => { bleIn = f; },
    close: () => { bleIn = null; A.bleClose(); },
  });
  try { dev.bank = await dev.readBank(); } catch (e) { A.bleClose(); throw e; }
  dev.portName = `${pedal.name} (Bluetooth)`;
  androidBleName = dev.portName;
  dev.access = androidAccess;
  dev.bluetooth = true;
  return dev;
}

async function openAndroidMidi(port) {
  const all = JSON.parse(globalThis.AndroidMidi.list());
  const pedals = androidBluetoothPedals();
  const wanted = port.endsWith(" (Bluetooth)") ? pedals.filter(p => `${p.name} (Bluetooth)` === port) : [];
  if (wanted.length || (!all.length && pedals.length && !port)) {
    let error;
    for (const p of (wanted.length ? wanted : pedals)) {
      try { return await openAndroidBle(p); } catch (e) { error = e; }
    }
    throw error;
  }
  if (!all.length) throw new DeviceError("No se ve la Tank-G. Conéctala por USB-OTG o emparéjala por Bluetooth en los ajustes de Android.");
  const devices = choose(all, port);
  if (!devices.length) throw new DeviceError("No se ve ningún dispositivo MIDI. ¿La Tank-G está conectada por USB-OTG y encendida?");
  let error;
  for (const d of devices) {
    try {
      await androidOpen(d.id);
      const dev = new TankG({
        send: data => globalThis.AndroidMidi.send(toHex(data)),
        onMessage: f => { androidIn = f; },
        close: () => { androidIn = null; globalThis.AndroidMidi.close(); },
      });
      dev.bank = await dev.readBank(2);
      dev.portName = d.name;
      dev.access = androidAccess;
      return dev;
    } catch (e) { globalThis.AndroidMidi.close(); error = e; }
  }
  throw error;
}

/** In-memory pedal with the behaviour observed on the real one (tests/test_tankg.py FakePedal). */
export function fakePedal(image, { dropWrites = false, latency = 15 } = {}) {
  const mem = Uint8Array.from(image);
  let cb = null;
  const reply = msg => setTimeout(() => cb?.(msg), latency);
  const pedal = {
    mem, dropWrites, sent: [],
    send(data) {
      pedal.sent.push(Uint8Array.from(data));
      if (data[0] !== 0xf0) return;
      const f = parse(data);
      if (f.cls === CLS_READ) {
        reply(build(CLS_READ, CMD_READ + 8 * f.length, f.field, f.length, f.space, mem.slice(f.field, f.field + f.length)));
      } else if (f.cls === CLS_WRITE) {
        if (f.space === 0 && f.length && !pedal.dropWrites) mem.set(f.payload, f.field);
        reply(ACK);
      }
    },
    onMessage: f => { cb = f; },
    close: () => { cb = null; },
  };
  return pedal;
}

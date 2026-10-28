// AMP models (.am4data) for the TANK-G v2: a 1:1 port of tankg/am4.py (research/FINDINGS.md §9).
// A file is 7868 bytes ("AM4\0", a name, the float32 weights of a 16-unit GRU at 0x83C). Before the
// upload M-EFCS appends an "LMT\0" block: the GRU state after one second of a decaying input,
// computed in Q21 fixed point with 512-entry sigmoid/tanh tables. lmt() reproduces it bit for bit
// (checked against Python by tests/ui/parity.test.mjs).

export const FILE_LEN = 7868, LMT_LEN = 68, UPLOAD_LEN = FILE_LEN + LMT_LEN, EXTENSION = ".am4data";

const WEIGHTS = 0x83c, H = 16, Q = 2 ** 21, STEPS = 44100;
const f32bits = u => new DataView(Uint32Array.of(u).buffer).getFloat32(0, true);
const QF = f32bits(0x49fffff8);                                 // 2097151.0
const C1 = f32bits(0xc0dd0c55), C2 = f32bits(0x383e37c6);       // ln(0.001), 1/22050
const fr = Math.fround;

function table(f, clamp = 0) {
  let q = Array.from({ length: 513 }, (_, i) => Math.trunc(f(-16 + i / 16) * 2 ** 23));
  if (clamp) q = q.map(v => Math.max(-clamp, Math.min(clamp, v)));
  return [q.slice(0, 512), q.slice(0, 512).map((v, i) => q[i + 1] - v)];
}
export const SIG = table(x => 1 / (1 + Math.exp(-x)));
export const TANH = table(Math.tanh, 2 ** 23 - 1);

function act(v, [tab, delta]) {
  v = Math.max(-0x2000000, Math.min(0x1ffffff, v));
  const i = (v + 0x2000000) >>> 17;
  return Math.floor((tab[i] + Math.floor(((v & 0x1ffff) * delta[i]) / 131072)) / 4) | 0;
}

/** Σ a[k]·b[k] >> 21 as int32; exact (BigInt) when a double could lose precision. */
function dot(a, b, n) {
  let acc = 0, safe = true;
  for (let k = 0; k < n; k++) {
    const p = a[k] * b[k];
    acc += p;
    if (Math.abs(p) >= 2 ** 53 || Math.abs(acc) >= 2 ** 53) safe = false;
  }
  if (safe) return Math.floor(acc / Q) | 0;
  let big = 0n;
  for (let k = 0; k < n; k++) big += BigInt(a[k]) * BigInt(b[k]);
  return Number(BigInt.asIntN(32, big >> 21n));
}

/** The 68-byte LMT block M-EFCS appends to a model before uploading it (same as am4.lmt). */
export function lmt(data) {
  const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const q = Array.from({ length: 928 }, (_, i) => Math.trunc(fr(dv.getFloat32(WEIGHTS + 4 * i, true) * QF)));
  const rows = [];
  for (let g = 0; g < 3; g++)
    for (let j = 0; j < H; j++) rows.push([...q.slice(48 + 256 * g + 16 * j, 48 + 256 * g + 16 * j + H), q[16 * g + j]]);
  const wr = rows.slice(0, H), wz = rows.slice(H, 2 * H), wn = rows.slice(2 * H);
  const bIh = [0, 1, 2].map(g => q.slice(816 + 16 * g, 816 + 16 * g + H));
  const bHh = [0, 1, 2].map(g => q.slice(864 + 16 * g, 864 + 16 * g + H));
  const br = bIh[0].map((v, j) => (v + bHh[0][j]) | 0), bz = bIh[1].map((v, j) => (v + bHh[1][j]) | 0);
  let h = new Array(H).fill(0);
  const v = new Array(H + 1), r = new Array(H), z = new Array(H), n = new Array(H);
  for (let step = 0; step < STEPS; step++) {
    const x = Math.trunc(fr(fr(Math.exp(fr(fr(step * C1) * C2))) * QF));
    for (let j = 0; j < H; j++) v[j] = h[j];
    v[H] = x;
    for (let j = 0; j < H; j++) {
      r[j] = act((dot(wr[j], v, H + 1) + br[j]) | 0, SIG);
      z[j] = act((dot(wz[j], v, H + 1) + bz[j]) | 0, SIG);
    }
    for (let j = 0; j < H; j++) {
      const hn = (dot(wn[j], h, H) + bHh[2][j]) | 0;
      const pre = Math.floor((wn[j][H] * x + r[j] * hn) / Q) | 0;
      n[j] = act((pre + bIh[2][j]) | 0, TANH);
    }
    h = h.map((hj, j) => (Math.floor(((hj - n[j]) * z[j]) / Q) + n[j]) | 0);
  }
  const out = new Uint8Array(LMT_LEN), o = new DataView(out.buffer);
  out.set([0x4c, 0x4d, 0x54, 0x00]);
  h.forEach((val, j) => o.setFloat32(4 + 4 * j, val / Q, true));
  return out;
}

const isAm4 = d => d[0] === 0x41 && d[1] === 0x4d && d[2] === 0x34 && d[3] === 0x00;

/** Throws when `data` is not a Tank-G AMP model (same checks as am4.check). */
export function check(data) {
  if (!isAm4(data) || (data.length !== FILE_LEN && data.length !== UPLOAD_LEN))
    throw new Error("No es un modelo de AMP para la Tank-G (archivo .am4data de M-EFCS).");
  if (data.length === UPLOAD_LEN && !(data[FILE_LEN] === 0x4c && data[FILE_LEN + 1] === 0x4d && data[FILE_LEN + 2] === 0x54 && data[FILE_LEN + 3] === 0))
    throw new Error("Archivo .am4data dañado (bloque final desconocido).");
}

/** The 7936 bytes sent to the pedal: the model plus its LMT block (kept if already there). */
export function uploadPayload(data) {
  check(data);
  if (data.length === UPLOAD_LEN) return Uint8Array.from(data);
  const out = new Uint8Array(UPLOAD_LEN);
  out.set(data);
  out.set(lmt(data), FILE_LEN);
  return out;
}

/** Readable name from the file name (M-EFCS downloads are prefixed with a UUID). */
export function nameFromPath(name) {
  let stem = name.split(/[\\/]/).pop();
  stem = stem.toLowerCase().endsWith(EXTENSION) ? stem.slice(0, -EXTENSION.length) : stem.replace(/\.[^.]*$/, "");
  stem = stem.replace(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_/i, "");
  return stem.replace(/_/g, " ").replace(/\s+/g, " ").trim().slice(0, 40);
}

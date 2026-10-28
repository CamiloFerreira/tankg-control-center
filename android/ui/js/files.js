// File formats shared with the desktop app (tankg/library.py): the files are interchangeable.
//   .tgbank    raw 758-byte bank (M-EFCS tankG_*_preset.bin loads too)
//   .tgpreset  JSON {format: "tankg-preset", version, name, raw (hex), amp, cab, source_slot, saved}
//   .tgset     JSON {format: "tankg-set", version, title, presets: [{slot, name, raw}]}
//   .tgpack    JSON {format: "tankg-pack", version, title, presets: [{slot, name, raw}], banks: {"3": name},
//              amps: [{slot: 1-9, name, data: .am4data base64 | community: {article, file}, credit}]}   (tankg/pack.py)
import { AMP_MODELS, CAB_MODELS } from "./data.js";
import { Bank, fromHex, slotName, toHex } from "./protocol.js";
import { check as checkAm4 } from "./am4.js";

export const PRESET_FORMAT = "tankg-preset", SET_FORMAT = "tankg-set";

const localIso = (d = new Date()) => {
  const z = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`;
};
export const stamp = (d = new Date()) => localIso(d).replace(/[-:]/g, "").replace("T", "-");

export function presetFile(record, slot, name) {
  return JSON.stringify({
    format: PRESET_FORMAT, version: 1, name: name || null, raw: toHex(record),
    amp: AMP_MODELS[record[5]] ?? `? (${record[5]})`, cab: CAB_MODELS[record[17]] ?? `? (${record[17]})`,
    source_slot: slot === null || slot === undefined ? null : slotName(slot), saved: localIso(),
  }, null, 2) + "\n";
}

export function parsePresetFile(text) {
  let doc;
  try { doc = JSON.parse(text); } catch { throw new Error("No es un archivo .tgpreset válido."); }
  if (doc?.format !== PRESET_FORMAT) throw new Error(`Formato desconocido: ${JSON.stringify(doc?.format)}`);
  const raw = fromHex(String(doc.raw || ""));
  if (raw.length !== 21) throw new Error("El preset debe tener 21 bytes.");
  return { record: raw, name: doc.name || null };
}

export function setFile(bank, slots, names, title) {
  return JSON.stringify({
    format: SET_FORMAT, version: 1, title: title || null,
    presets: slots.map((s, i) => ({ slot: slotName(s), name: names[i] || null, raw: toHex(bank.presets[s]) })),
  }, null, 2) + "\n";
}

export function parseSetFile(text) {
  let doc;
  try { doc = JSON.parse(text); } catch { throw new Error("No es un archivo .tgset válido."); }
  if (doc?.format !== SET_FORMAT) throw new Error(`Formato desconocido: ${JSON.stringify(doc?.format)}`);
  const items = (doc.presets || []).map(it => ({ record: fromHex(String(it.raw)), name: it.name || null }));
  if (!items.length) throw new Error("El archivo no contiene presets.");
  if (items.some(it => it.record.length !== 21)) throw new Error("Algún preset no tiene 21 bytes.");
  return { title: doc.title || null, items };
}

export const parseBankFile = bytes => Bank.fromBytes(bytes);

// preset packs: presets + the AMP models they use (tankg/pack.py) -----------------------------------

export const PACK_FORMAT = "tankg-pack", PACK_EXTENSION = ".tgpack";
export const toBase64 = bytes => { let b = ""; bytes.forEach(v => { b += String.fromCharCode(v); }); return btoa(b); };
export const fromBase64 = text => Uint8Array.from(atob(text), c => c.charCodeAt(0));
const parseSlot = t => (/^[1-9][ABCD]$/i.test(t) ? (Number(t[0]) - 1) * 4 + "ABCD".indexOf(t[1].toUpperCase()) : Number(t));

/** The pack for `slots` and the uploaded AMP slots used by them whose model this device lacks (same as pack.make). */
export function packFile(bank, slots, presetNames, bankNames, ampNames, models, title) {
  const used = [...new Set(slots.map(s => bank.presets[s][5]))].sort((a, b) => a - b);
  const custom = used.filter(a => ampNames[String(a + 1)]);
  const whole = [...new Set(slots.map(s => Math.floor(s / 4)))].filter(b => [0, 1, 2, 3].every(i => slots.includes(b * 4 + i)));
  const doc = {
    format: PACK_FORMAT, version: 1, title: title || null,
    presets: slots.map(s => ({ slot: slotName(s), name: presetNames[s] || null, raw: toHex(bank.presets[s]) })),
    banks: Object.fromEntries(whole.sort((a, b) => a - b).filter(b => bankNames[String(b + 1)]).map(b => [String(b + 1), bankNames[String(b + 1)]])),
    amps: custom.filter(a => models[a]).map(a => ({ slot: a + 1, name: ampNames[String(a + 1)], data: toBase64(models[a]) })),
  };
  return { text: JSON.stringify(doc, null, 1) + "\n", missing: custom.filter(a => !models[a]) };
}

export function parsePackFile(text) {
  let doc;
  try { doc = JSON.parse(text); } catch { throw new Error("No es un archivo .tgpack válido."); }
  if (doc?.format !== PACK_FORMAT) throw new Error("No es un pack de Tank-G (.tgpack).");
  const presets = (doc.presets || []).map(it => {
    const record = fromHex(String(it.raw || ""));
    if (record.length !== 21) throw new Error("Algún preset del pack no tiene 21 bytes.");
    return { slot: parseSlot(String(it.slot || "1A")), record, name: it.name || null };
  });
  if (!presets.length) throw new Error("El pack no contiene presets.");
  const amps = (doc.amps || []).map(it => {
    const slot = Number(it.slot) - 1;
    if (!(slot >= 0 && slot < AMP_MODELS.length)) throw new Error("Un modelo de AMP del pack tiene un espacio inválido.");
    const amp = { slot, name: String(it.name || `AMP ${slot + 1}`), data: null, community: null, credit: it.credit || null };
    if (it.community && !it.data) {   // a reference to the M-VAVE community: downloaded when imported (pack.py)
      if (!(Number(it.community.article) > 0 && it.community.file)) throw new Error("Un modelo de AMP del pack tiene una referencia inválida.");
      amp.community = { article: Number(it.community.article), file: String(it.community.file) };
    } else {
      amp.data = fromBase64(String(it.data || ""));
      checkAm4(amp.data);
    }
    return amp;
  });
  const kind = { 1: "preset", 4: "bank", 36: "all" }[presets.length] || "set";
  return { title: doc.title || null, presets, amps, banks: { ...(doc.banks || {}) }, kind };
}

/** Records with the TYPE of moved models changed ({old slot: new slot}, 0-8), like pack.remap. */
export const remapPack = (records, moves) => records.map(r => {
  const q = Uint8Array.from(r);
  if (q[5] in moves) q[5] = moves[q[5]];
  return q;
});

export const COMMUNITY_DOWNLOAD = "https://community.m-vave.com/bbs/api/download";
export const communityUrl = ref => `${COMMUNITY_DOWNLOAD}?articleId=${ref.article}&file=${encodeURIComponent(ref.file)}`;
export const communityKey = ref => `${ref.article}:${ref.file}`;
export const creditText = amp => (amp.credit?.author ? `«${amp.credit.title || amp.name}» de ${amp.credit.author} (${amp.credit.source || ""})` : "");

// File formats shared with the desktop app (tankg/library.py): the files are interchangeable.
//   .tgbank    raw 758-byte bank (M-EFCS tankG_*_preset.bin loads too)
//   .tgpreset  JSON {format: "tankg-preset", version, name, raw (hex), amp, cab, source_slot, saved}
//   .tgset     JSON {format: "tankg-set", version, title, presets: [{slot, name, raw}]}
import { AMP_MODELS, CAB_MODELS } from "./data.js";
import { Bank, fromHex, slotName, toHex } from "./protocol.js";

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

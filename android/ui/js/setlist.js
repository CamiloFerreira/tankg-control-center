// Setlists (same as tankg/setlist.py, checked against it by tests/test_ui.py): the songs of a show,
// saved with the preset names (aliases.setlists, synced through the cloud), played in stage mode and
// optionally put in footswitch order from a starting slot. A song remembers its preset's slot, bytes
// and name, so resolve() finds it again after presets move; ordering swaps each song into its place.
import { AMP_MODELS } from "./data.js";
import { Bank, SLOTS, slotName, toHex } from "./protocol.js";

/** A setlist entry for the preset now in `slot`. */
export const song = (bank, names, slot, note = "") =>
  ({ slot: slotName(slot), raw: toHex(bank.presets[slot]), name: names[slotName(slot)] || "", note });

/** Current slot of each song (null = no preset matches any more): bytes count most, then name, then slot. */
export function resolve(songs, bank, names) {
  const used = new Set();
  return songs.map(s => {
    let best = null, bestScore = 1;
    for (let slot = 0; slot < SLOTS; slot++) {
      if (used.has(slot)) continue;
      const score = 4 * (toHex(bank.presets[slot]) === s.raw) + 2 * (!!s.name && names[slotName(slot)] === s.name)
        + (slotName(slot) === s.slot);
      if (score > bestScore) { best = slot; bestScore = score; }
    }
    if (best !== null) used.add(best);
    return best;
  });
}

/** The songs pointing to where their presets are now (unmatched ones are kept as they were). */
export const refresh = (songs, bank, names) =>
  resolve(songs, bank, names).map((slot, i) => (slot !== null ? song(bank, names, slot, songs[i].note || "") : { ...songs[i] }));

/** source[new slot] = old slot after placing `order` (old slots, no repeats) at start, start+1… */
export function layout(order, start = 0) {
  if (new Set(order).size !== order.length || order.some(s => !(s >= 0 && s < SLOTS)))
    throw new Error("setlist con slots repetidos o fuera de rango");
  if (start < 0 || start + order.length > SLOTS)
    throw new Error(`no entran ${order.length} canciones desde ${slotName(Math.min(Math.max(start, 0), SLOTS - 1))}`);
  const source = [...Array(SLOTS).keys()];
  order.forEach((s, i) => {
    const j = source.indexOf(s);
    [source[start + i], source[j]] = [source[j], source[start + i]];
  });
  return source;
}

export const apply = (bank, source) => new Bank(source.map(s => Uint8Array.from(bank.presets[s])));

/** Per-slot data keyed by slot name ("6A": …) after the move. */
export const moveNames = (names, source) =>
  Object.fromEntries(source.flatMap((old, s) => (slotName(old) in names ? [[slotName(s), names[slotName(old)]]] : [])));

/** What the song is called: its preset name, else its AMP model (like the preset list). */
export function label(s) {
  const amp = (s.raw || "").length >= 12 ? parseInt(s.raw.slice(10, 12), 16) : -1;
  return s.name || (amp >= 0 && amp < AMP_MODELS.length ? AMP_MODELS[amp] : `Preset ${s.slot ?? "?"}`);
}

/** The setlist to print or share: song number, slot to step on, name and note. */
export function text(title, songs, slots) {
  const lines = [title.trim() ? `SETLIST · ${title.trim()}` : "SETLIST", ""];
  songs.forEach((s, i) => {
    const note = (s.note || "").trim();
    lines.push(`${String(i + 1).padStart(2)}. ${slots[i] !== null ? slotName(slots[i]) : "--"}  ${label(s)}` + (note ? `  (${note})` : ""));
  });
  return lines.join("\n") + "\n";
}

const SLOT_RE = /^[1-9][ABCD]$/;
/** Setlists read from storage or the cloud, keeping only well-formed entries (slots like "6A"). */
export const clean = doc => (Array.isArray(doc) ? doc : []).filter(sl => sl && typeof sl === "object").map(sl => ({
  title: String(sl.title || "Setlist"),
  songs: (sl.songs || []).filter(s => s && SLOT_RE.test(String(s.slot)) && /^([0-9a-f]{2})*$/i.test(String(s.raw)))
    .map(s => ({ slot: String(s.slot), raw: String(s.raw), name: String(s.name || ""), note: String(s.note || "") })),
}));

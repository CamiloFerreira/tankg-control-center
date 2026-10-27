// "Crear con IA" for the Android app: a port of the runtime part of tankg/ai.py. The prompt,
// schemas, instructions and provider list come from data.js (generated from ai.py), so a prompt
// change in Python reaches every platform; only the request/parsing code lives here.
import { AI, FIELDS } from "./data.js";

const F = Object.fromEntries(FIELDS.map(f => [f.key, f]));
export class AIError extends Error {}

const clamp = (key, v) => Math.max(0, Math.min(F[key].max, Math.trunc(Number(v)) || 0));

/** Knob position inside one third of a three-zone knob (same as ai._zone_value). */
export function zoneValue(zone, amount) {
  const lo = Math.floor((zone * 128) / 3) + 4, hi = Math.floor(((zone + 1) * 128) / 3) - 5;
  const a = Math.max(0, Math.min(100, amount));
  return lo + pyRound((a * (hi - lo)) / 100);
}
const pyRound = x => {   // Python's round(): halves go to the even neighbour
  const f = Math.floor(x), d = x - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
};

/** Design -> 21-byte record; unmapped bytes are kept from `like` (same as ai.apply_design). */
export function applyDesign(design, like = null) {
  const p = like ? Uint8Array.from(like) : new Uint8Array(21);
  const set = (key, v) => { p[F[key].offset] = v; };
  for (const key of ["amp_type", "gain", "treble", "middle", "bass", "volume", "gate", "cab", "mod_speed", "dly_time", "rvb_mix"])
    set(key, clamp(key, design[key]));
  for (const key of ["amp_on", "mod_on", "dly_on", "rvb_on"]) set(key, design[key] ? 1 : 0);
  for (const [prefix, field, amount] of [["mod", "mod_fx", "mod_amount"], ["dly", "dly_mix", "dly_mix"], ["rvb", "rvb_decay", "rvb_decay"]]) {
    const zone = Math.max(0, AI.zones[prefix].indexOf(design[`${prefix}_type`]));
    set(field, zoneValue(zone, Math.trunc(Number(design[amount])) || 0));
  }
  const color = [...(design.led_color || [255, 255, 255]), 255, 255, 255].slice(0, 3);
  p.set(color.map(c => Math.max(0, Math.min(255, Math.trunc(Number(c)) || 0))), 18);
  return p;
}

const userPrompt = (description, instrument, bank) =>
  `Instrumento: ${instrument}\nSonido deseado: ${description.trim()}` + (bank ? `\n\n${AI.bankInstructions}` : "");

/** Self-contained prompt for a chat web page (same text as ai.web_prompt). */
export function webPrompt(description, instrument, bank = false) {
  const keys = AI.schema.required.map(k => `"${k}"`).join(", ");
  const shape = bank
    ? `un objeto con "bank_name" (texto) y "presets": una lista de EXACTAMENTE 4 objetos (A, B, C, D), cada uno con exactamente estas claves: ${keys}`
    : `exactamente estas claves: ${keys}`;
  return `${AI.system}\n\n${userPrompt(description, instrument, bank)}\n\n` +
    "Responde ÚNICAMENTE con un bloque de código JSON (```json ... ```) que contenga " +
    `${shape}. Tipos: amp_on/mod_on/dly_on/rvb_on booleanos; mod_type uno de ` +
    "chorus|phaser|tremolo; dly_type uno de analog|tape|dual; rvb_type uno de room|spring|cloud; " +
    "led_color lista [R, G, B] de 0 a 255; el resto números enteros en los rangos indicados; " +
    "name y explanation en español.";
}

function jsonCandidates(text) {
  const found = [...text.matchAll(/```(?:json)?\s*(\{[\s\S]*?\})\s*```/g)].map(m => m[1]);
  const start = text.indexOf("{");
  if (start >= 0) {
    let depth = 0;
    for (let i = start; i < text.length; i++) {
      if (text[i] === "{") depth++;
      if (text[i] === "}") depth--;
      if (depth === 0) { found.push(text.slice(start, i + 1)); break; }
    }
  }
  const docs = [];
  for (const c of found) { try { const d = JSON.parse(c); if (d && typeof d === "object" && !Array.isArray(d)) docs.push(d); } catch { /* not JSON */ } }
  return docs;
}

const complete = d => AI.schema.required.every(k => k in d);

function build(design, like) {
  const missing = AI.schema.required.filter(k => !(k in design));
  if (missing.length) throw new AIError(`Al preset de la IA le faltan campos: ${missing.join(", ")}`);
  return { bytes: applyDesign(design, like), name: String(design.name).slice(0, 40), explanation: String(design.explanation) };
}

function buildBank(doc, likes) {
  const designs = doc.presets;
  if (!Array.isArray(designs) || designs.length < 4) throw new AIError("La IA no devolvió los 4 presets del banco.");
  return { bankName: String(doc.bank_name || "").slice(0, 24), items: designs.slice(0, 4).map((d, i) => build(d, likes[i])) };
}

/** Browser mode: the preset (or bank) inside the answer the user copied from the chat. */
export function fromText(text, bank, likes) {
  const docs = jsonCandidates(text);
  if (bank) {
    const doc = docs.find(d => Array.isArray(d.presets) && d.presets.length >= 4 && d.presets.slice(0, 4).every(p => p && complete(p)));
    if (!doc) throw new AIError("No encontré los 4 presets del banco en el texto copiado. Copia la respuesta completa.");
    return buildBank(doc, likes);
  }
  const design = docs.find(complete);
  if (!design) throw new AIError("No encontré el preset en el texto copiado. Copia la respuesta completa de la IA (el bloque JSON).");
  return build(design, likes[0]);
}

// API mode -----------------------------------------------------------------------------------

/** POST JSON through the APK's native bridge (no CORS limits, local servers work). */
async function post(url, headers, body) {
  const { status, text } = await androidPost(url, headers, body);
  if (status === 0) throw new AIError(`No se pudo conectar con ${url}: ${text}`);
  let data = null;
  try { data = JSON.parse(text); } catch { /* not JSON */ }
  if (status >= 400) {
    let detail = data?.error ?? "";
    if (detail && typeof detail === "object") detail = detail.message ?? "";
    const hint = { 401: "clave de API inválida", 403: "sin permiso para este modelo", 404: "modelo o URL no encontrados", 429: "límite de uso o saldo agotado" }[status] || "";
    throw new AIError(`Error ${status} del servicio de IA${hint ? `: ${hint}` : ""}. ${detail}`.trim());
  }
  if (!data) throw new AIError("La respuesta del servicio de IA no era JSON.");
  return data;
}

const pending = new Map();
let nextId = 1;
globalThis.__httpDone = (id, status, text) => { pending.get(id)?.({ status, text }); pending.delete(id); };
function androidPost(url, headers, body) {
  return new Promise(resolve => {
    const id = nextId++;
    pending.set(id, resolve);
    globalThis.AndroidMidi.httpPost(id, url, JSON.stringify({ "content-type": "application/json", ...headers }), JSON.stringify(body));
  });
}

const withoutLimits = s => (Array.isArray(s) ? s.map(withoutLimits) : s && typeof s === "object"
  ? Object.fromEntries(Object.entries(s).filter(([k]) => !["minimum", "maximum", "minItems", "maxItems"].includes(k)).map(([k, v]) => [k, withoutLimits(v)]))
  : s);

async function askClaude(cfg, prompt, bank) {
  const schema = bank ? AI.bankSchema : AI.schema, tool = bank ? "crear_banco" : "crear_preset";
  const data = await post(`${cfg.baseUrl}/v1/messages`,
    { "x-api-key": cfg.key, "anthropic-version": "2023-06-01" },
    { model: cfg.model, max_tokens: bank ? 8192 : 2048, system: AI.system,
      tools: [{ name: tool, description: "Devuelve el resultado para la Tank-G", input_schema: schema }],
      tool_choice: { type: "tool", name: tool }, messages: [{ role: "user", content: prompt }] });
  const block = (data.content || []).find(b => b.type === "tool_use");
  if (!block) throw new AIError("La respuesta de Claude no contenía un preset.");
  return block.input;
}

async function askOpenAI(cfg, prompt, bank, strict = true) {
  const schema = bank ? AI.bankSchema : AI.schema;
  const fmt = strict ? { type: "json_schema", json_schema: { name: "preset", schema: withoutLimits(schema), strict: true } } : { type: "json_object" };
  const extra = strict ? "" : "\nResponde solo con un objeto JSON con estas claves: " + schema.required.join(", ") +
    (bank ? "; cada elemento de presets con: " + AI.schema.required.join(", ") : "");
  let data;
  try {
    data = await post(`${cfg.baseUrl}/chat/completions`, cfg.key ? { authorization: `Bearer ${cfg.key}` } : {},
      { model: cfg.model, response_format: fmt, messages: [{ role: "system", content: AI.system + extra }, { role: "user", content: prompt }] });
  } catch (e) {
    if (strict && cfg.provider === "compatible") return askOpenAI(cfg, prompt, bank, false);   // many local servers lack json_schema
    throw e;
  }
  try { return JSON.parse(data.choices[0].message.content); }
  catch { throw new AIError("La respuesta del modelo no era un preset JSON válido."); }
}

/** cfg: {provider, key, model, baseUrl}. Returns {bytes, name, explanation} or {bankName, items}. */
export async function generate(cfg, description, instrument, bank, likes) {
  const p = AI.providers[cfg.provider];
  cfg = { ...cfg, model: cfg.model || p.model, baseUrl: (cfg.baseUrl || p.url).replace(/\/+$/, "") };
  if (cfg.provider !== "compatible" && !cfg.key) throw new AIError(`Falta la clave de API de ${p.label}.`);
  const prompt = userPrompt(description, instrument, bank);
  const doc = cfg.provider === "claude" ? await askClaude(cfg, prompt, bank) : await askOpenAI(cfg, prompt, bank);
  return bank ? buildBank(doc, likes) : build(doc, likes[0]);
}

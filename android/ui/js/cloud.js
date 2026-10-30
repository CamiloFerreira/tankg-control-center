// Google Drive sync for the APK: same files and format as tankg/cloud.py (folder "Tank-G Control
// Center": tankg-cloud.json + tankg-history-<stamp>.json, newest 30 kept). Sign-in with Google's
// device flow (google.com/device + a code): the code is copied and the page opened for the user.
// The OAuth client comes from js/secrets.js, written by android/build.sh (never committed).
import { Bank, fromHex, toHex } from "./protocol.js";
import { clean as cleanSetlists } from "./setlist.js";

const CLOUD = await import("./secrets.js").then(m => m.CLOUD || {}, () => ({}));
const A = globalThis.AndroidMidi;
const SCOPE = "https://www.googleapis.com/auth/drive.file";
const FOLDER = "Tank-G Control Center", FOLDER_MIME = "application/vnd.google-apps.folder";
const FILES = "https://www.googleapis.com/drive/v3/files";
const UPLOAD = "https://www.googleapis.com/upload/drive/v3/files";
export const LATEST = "tankg-cloud.json";
const HISTORY_PREFIX = "tankg-history-", HISTORY_KEEP = 30, FORMAT = "tankg-cloud";

export class CloudError extends Error {}
/** Google could not be reached (transient: no network, app in the background). */
export class NetworkError extends CloudError {}
export const configured = () => !!(CLOUD.clientId && CLOUD.clientSecret);

const pending = new Map();
let nextId = 100000;
const prevDone = globalThis.__httpDone;
globalThis.__httpDone = (id, status, text) => {
  if (pending.has(id)) { pending.get(id)({ status, text }); pending.delete(id); } else prevDone?.(id, status, text);
};
function http(method, url, headers = {}, body = "") {
  return new Promise(resolve => {
    const id = nextId++;
    pending.set(id, resolve);
    A.httpRequest(id, method, url, JSON.stringify(headers), body);
  });
}
/** GET of a binary file through the APK bridge (status, bytes); used for the community AMP models. */
export async function getBinary(url) {
  const r = await http("GET", url, { "X-Tankg-Base64": "1", "User-Agent": "Tank-G Control Center" });
  return { status: r.status, bytes: r.status === 200 ? Uint8Array.from(atob(r.text), c => c.charCodeAt(0)) : null };
}
const form = fields => Object.entries(fields).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
const json = t => { try { return JSON.parse(t || "{}"); } catch { return {}; } };

async function postForm(url, fields) {
  const r = await http("POST", url, { "Content-Type": "application/x-www-form-urlencoded" }, form(fields));
  if (r.status === 0) throw new NetworkError("Sin conexión con Google. ¿Hay internet?");
  return { status: r.status, doc: json(r.text) };
}

// sign-in (device flow) ------------------------------------------------------------------------

export async function startSignIn() {
  if (!configured()) throw new CloudError("La sincronización con Google Drive no está configurada en esta versión.");
  const { status, doc } = await postForm("https://oauth2.googleapis.com/device/code", { client_id: CLOUD.clientId, scope: SCOPE });
  if (status !== 200) throw new CloudError(`Google rechazó el inicio de sesión: ${doc.error_description || doc.error || status}`);
  return { deviceCode: doc.device_code, userCode: doc.user_code, url: doc.verification_url || doc.verification_uri,
    interval: doc.interval || 5, expiresIn: doc.expires_in || 1800 };
}

export async function finishSignIn(code, shouldStop = () => false) {
  const end = Date.now() + code.expiresIn * 1000;
  let interval = code.interval;
  while (Date.now() < end) {
    if (shouldStop()) throw new CloudError("Inicio de sesión cancelado.");
    await new Promise(r => {   // wait, but ask at once when the user comes back from the browser
      const doc = globalThis.document;
      const back = () => { if (doc.visibilityState === "visible") done(); };
      const done = () => { clearTimeout(t); doc?.removeEventListener("visibilitychange", back); r(); };
      const t = setTimeout(done, interval * 1000);
      doc?.addEventListener("visibilitychange", back);
    });
    let status, doc;
    try {
      ({ status, doc } = await postForm("https://oauth2.googleapis.com/token", { client_id: CLOUD.clientId,
        client_secret: CLOUD.clientSecret, device_code: code.deviceCode, grant_type: "urn:ietf:params:oauth:grant-type:device_code" }));
    } catch (e) {
      if (e instanceof NetworkError) continue;   // Android cuts the network of apps in the background
      throw e;
    }
    if (status === 200 && doc.refresh_token) return doc.refresh_token;
    if (doc.error === "authorization_pending") continue;
    if (doc.error === "slow_down") { interval += 5; continue; }
    if (doc.error === "access_denied") throw new CloudError("Acceso denegado en Google.");
    throw new CloudError(`No se pudo iniciar sesión: ${doc.error_description || doc.error || status}`);
  }
  throw new CloudError("El código caducó: vuelve a intentarlo.");
}

// Drive --------------------------------------------------------------------------------------

export class Drive {
  constructor(refreshToken) { this.refresh = refreshToken; this.access = ""; this.expires = 0; this.folderId = ""; }

  async token() {
    if (this.access && Date.now() < this.expires - 60000) return this.access;
    const { status, doc } = await postForm("https://oauth2.googleapis.com/token", { client_id: CLOUD.clientId,
      client_secret: CLOUD.clientSecret, refresh_token: this.refresh, grant_type: "refresh_token" });
    if (status !== 200) throw new CloudError("La sesión de Google caducó o fue revocada: vuelve a conectar con Google Drive.");
    this.access = doc.access_token;
    this.expires = Date.now() + (doc.expires_in || 3600) * 1000;
    return this.access;
  }

  async call(method, url, body = "", type = "") {
    const headers = { Authorization: `Bearer ${await this.token()}` };
    if (type) headers["Content-Type"] = type;
    if (method === "PATCH") { method = "POST"; headers["X-HTTP-Method-Override"] = "PATCH"; }   // HttpURLConnection has no PATCH
    const r = await http(method, url, headers, body);
    if (r.status === 0) throw new NetworkError("Sin conexión con Google. ¿Hay internet?");
    if (r.status >= 400) throw new CloudError(`Google Drive respondió: ${json(r.text).error?.message || r.status}`);
    return r.text;
  }

  async query(q) {
    const params = form({ q, pageSize: 200, fields: "files(id,name,modifiedTime)", orderBy: "name desc" });
    return json(await this.call("GET", `${FILES}?${params}`)).files || [];
  }

  /** Id of the app's folder, created on first use. */
  async folder() {
    if (!this.folderId) {
      const found = await this.query(`name = '${FOLDER}' and mimeType = '${FOLDER_MIME}' and trashed = false`);
      this.folderId = found.length ? found[0].id
        : json(await this.call("POST", `${FILES}?fields=id`, JSON.stringify({ name: FOLDER, mimeType: FOLDER_MIME }), "application/json")).id;
    }
    return this.folderId;
  }

  async list() { return this.query(`'${await this.folder()}' in parents and trashed = false`); }

  async read(id) { return json(await this.call("GET", `${FILES}/${id}?alt=media`)); }

  async write(name, doc, id = null) {
    const payload = JSON.stringify(doc);
    if (id) { await this.call("PATCH", `${UPLOAD}/${id}?uploadType=media`, payload, "application/json"); return; }
    const b = "tankg-boundary";
    const body = `--${b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify({ name, parents: [await this.folder()] })}` +
      `\r\n--${b}\r\nContent-Type: application/json\r\n\r\n${payload}\r\n--${b}--`;
    await this.call("POST", `${UPLOAD}?uploadType=multipart`, body, `multipart/related; boundary=${b}`);
  }

  async remove(id) { await this.call("DELETE", `${FILES}/${id}`); }
}

// sync -----------------------------------------------------------------------------------------

/** Same as cloud.make_doc: "amps" (names of uploaded AMP models) only when there is one. */
export function makeDoc(bank, presets, banks, amps = {}, ampSources = {}, presetAmps = {}, setlists = []) {
  const aliases = { presets: { ...presets }, banks: { ...banks } };
  if (Object.keys(amps || {}).length) aliases.amps = { ...amps };
  if (Object.keys(ampSources || {}).length) aliases.ampSources = { ...ampSources };   // community origin of the models
  if (Object.keys(presetAmps || {}).length) aliases.presetAmps = { ...presetAmps };   // the captured amp of each pack preset
  if ((setlists || []).length) aliases.setlists = cleanSetlists(setlists);              // the saved shows (setlist.js)
  return { format: FORMAT, version: 1, updated: new Date().toISOString().replace(/\.\d+Z$/, "+00:00"),
    device: "Android", bank: toHex(bank.toBytes()), aliases };
}

export function parseDoc(doc) {
  if (doc?.format !== FORMAT) throw new CloudError("El archivo de la nube no es de Tank-G Control Center.");
  const a = doc.aliases || {};
  return { bank: Bank.fromBytes(fromHex(doc.bank)), presets: { ...(a.presets || {}) }, banks: { ...(a.banks || {}) },
    amps: { ...(a.amps || {}) }, ampSources: { ...(a.ampSources || {}) }, presetAmps: { ...(a.presetAmps || {}) },
    setlists: cleanSetlists(a.setlists) };
}

const sorted = v => (v && typeof v === "object" && !Array.isArray(v)
  ? Object.fromEntries(Object.keys(v).sort().map(k => [k, sorted(v[k])])) : v);
/** Identity of a version by content (presets and names), independent of its time. */
export async function docKey(doc) {
  const data = new TextEncoder().encode(JSON.stringify(sorted({ bank: doc.bank, aliases: doc.aliases })));
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
  return toHex(hash).slice(0, 16);
}

export async function push(drive, doc) {
  const files = await drive.list();
  const latest = files.find(f => f.name === LATEST);
  if (latest) {
    const old = await drive.read(latest.id);
    if (old.bank === doc.bank && JSON.stringify(sorted(old.aliases)) === JSON.stringify(sorted(doc.aliases))) return;
    const stamp = (old.updated || "").replace(/[-:]/g, "").slice(0, 15) || doc.updated.replace(/[-:]/g, "").slice(0, 15);
    await drive.write(`${HISTORY_PREFIX}${stamp}.json`, old);
  }
  await drive.write(LATEST, doc, latest?.id || null);
  const history = files.filter(f => f.name.startsWith(HISTORY_PREFIX)).sort((a, b) => b.name.localeCompare(a.name));
  for (const f of history.slice(HISTORY_KEEP - 1)) await drive.remove(f.id);
}

export async function pull(drive) {
  const latest = (await drive.list()).find(f => f.name === LATEST);
  return latest ? drive.read(latest.id) : null;
}

export async function history(drive) {
  const files = await drive.list();
  return [...files.filter(f => f.name === LATEST),
    ...files.filter(f => f.name.startsWith(HISTORY_PREFIX)).sort((a, b) => b.name.localeCompare(a.name))];
}

/** Same rule as cloud.startup_action: "same", "cloud", "local" (changes made here never reached the cloud
 *  and the cloud has not changed since: keep them and upload) or "conflict" (both changed: ask). */
export function startupAction(cloudKey, currentKey, synced, pendingKey) {
  if (pendingKey) {
    if (cloudKey === pendingKey) return "same";
    return !cloudKey || cloudKey === synced ? "local" : "conflict";
  }
  if (!cloudKey) return "local";   // first device: the cloud starts with this setup
  return cloudKey === currentKey ? "same" : "cloud";
}

export function when(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || "";
  const z = n => String(n).padStart(2, "0");
  return `${z(d.getDate())}-${z(d.getMonth() + 1)}-${d.getFullYear()} ${z(d.getHours())}:${z(d.getMinutes())}`;
}

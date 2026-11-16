// Diagnostics: port of tankg/diag.py (same texts and format, checked by tests/ui/tools.test.mjs).
// A short log of this session and a report to paste into a bug report or open as a GitHub issue.
// Only technical data: never preset or bank names, files, backups, the cloud session or API keys.
import { DIAG, RELEASES_REPO } from "./data.js";

const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
const KEY = /\b(?:sk-[\w-]{8,}|AIza[\w-]{20,}|ya29\.[\w.-]+|gh[pousr]_\w{20,})/g;
const log_ = [];
const errors_ = [];

/** Masks e-mail addresses and API keys/tokens. */
export const scrub = text => String(text).replace(EMAIL, "<correo>").replace(KEY, "<clave>");

/** The useful line of a message: the exception at the end of a traceback, else the first line. */
export function oneLine(text) {
  const lines = String(text).split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  if (!lines.length) return "";
  return (lines[0].startsWith("Traceback") ? lines[lines.length - 1] : lines[0]).slice(0, 300);
}

const stamp = () => new Date().toTimeString().slice(0, 8);
const push = (list, line, max) => { list.push(line); if (list.length > max) list.splice(0, list.length - max); };

export function log(event) {
  const line = oneLine(scrub(event));
  if (line) push(log_, `${stamp()} ${line}`, DIAG.maxLog);
}

export function error(message) {
  const line = oneLine(scrub(message));
  if (!line) return;
  push(errors_, `${stamp()} ${line}`, DIAG.maxErrors);
  push(log_, `${stamp()} Error: ${line}`, DIAG.maxLog);
}

export const lines = () => [...log_];
export const errors = () => [...errors_];

/** The report text (same fields as diag.report in Python). */
export function report(info) {
  const errs = info.errors || [], logLines = info.log || [];
  const out = [`Tank-G Control Center ${info.version ?? "?"}`,
    `Plataforma: ${info.platform || "?"}`,
    `Pedalera: ${info.pedal || "?"}`,
    `Puerto: ${info.port || "—"}`,
    `Modo demo: ${info.demo ? "sí" : "no"}`,
    `Presets sin guardar: ${info.modified || 0}`,
    `Nube: ${info.cloud ? "conectada" : "no"}`,
    `Backups: ${info.backups || 0}`,
    "",
    "Últimos errores:"];
  out.push(...(errs.length ? errs.map(e => `  ${e}`) : ["  (ninguno)"]));
  out.push("", `Registro de la sesión (${logLines.length} líneas):`);
  out.push(...(logLines.length ? logLines.map(l => `  ${l}`) : ["  (vacío)"]));
  return out.join("\n") + "\n";
}

/** Link that opens a new issue in the public repository with the template and the report. */
export function issueUrl(text) {
  text = text.trim();
  if (text.length > DIAG.issueChars) text = text.slice(0, DIAG.issueChars) + "\n…";
  const body = "**Qué pasó:**\n\n\n**Qué esperabas que pasara:**\n\n\n**Pasos para repetirlo:**\n1. \n\n" +
    "**Diagnóstico** (generado por la app; sin nombres de presets ni datos personales):\n```\n" + text + "\n```\n";
  return `https://github.com/${RELEASES_REPO}/issues/new?title=${encodeURIComponent("Problema: ")}&body=${encodeURIComponent(body)}`;
}

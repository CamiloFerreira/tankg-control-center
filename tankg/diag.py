"""Diagnostics shared by the desktop and the APK (android/ui/js/diag.js, same texts and format,
checked by tests/ui/tools.test.mjs): a short log of what happened in this session (connections, reads,
writes, errors) and a report to paste into a bug report or open as a GitHub issue.

Only technical data: version, platform, how the pedal is connected, counts and the log. Never preset
or bank names, file contents, backups, the cloud session or API keys; e-mail addresses, keys and the
home folder are masked (scrub) in everything that enters the log."""
from __future__ import annotations

import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote

from .version import RELEASES_REPO

MAX_LOG = 200        # lines kept in the session log
MAX_ERRORS = 5       # last errors shown at the top of the report
ISSUE_CHARS = 2500   # report text that fits in a GitHub "new issue" link
URL_SAFE = "!~*'()"  # what encodeURIComponent leaves as is, besides letters, digits and -_.

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_KEY = re.compile(r"\b(?:sk-[\w-]{8,}|AIza[\w-]{20,}|ya29\.[\w.-]+|gh[pousr]_\w{20,})")

_log: deque[str] = deque(maxlen=MAX_LOG)
_errors: deque[str] = deque(maxlen=MAX_ERRORS)


def scrub(text: str) -> str:
    """Masks e-mail addresses, API keys/tokens and the user's home folder."""
    text = _KEY.sub("<clave>", _EMAIL.sub("<correo>", str(text)))
    home = str(Path.home())
    return text.replace(home, "~") if len(home) > 1 else text


def one_line(text: str) -> str:
    """The useful line of a message: the exception at the end of a traceback, else the first line."""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        return ""
    return (lines[-1] if lines[0].startswith("Traceback") else lines[0])[:300]


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def log(event: str) -> None:
    line = one_line(scrub(event))
    if line:
        _log.append(f"{_stamp()} {line}")


def error(message: str) -> None:
    line = one_line(scrub(message))
    if line:
        _errors.append(f"{_stamp()} {line}")
        _log.append(f"{_stamp()} Error: {line}")


def lines() -> list[str]:
    return list(_log)


def errors() -> list[str]:
    return list(_errors)


def clear() -> None:
    _log.clear()
    _errors.clear()


def report(info: dict) -> str:
    """The report text. info: version, platform, pedal (connection state), port, demo, modified
    (presets not saved), cloud (connected), backups (count), errors and log (lists of lines)."""
    errs, log_lines = info.get("errors") or [], info.get("log") or []
    out = [f"Tank-G Control Center {info.get('version', '?')}",
           f"Plataforma: {info.get('platform') or '?'}",
           f"Pedalera: {info.get('pedal') or '?'}",
           f"Puerto: {info.get('port') or '—'}",
           f"Modo demo: {'sí' if info.get('demo') else 'no'}",
           f"Presets sin guardar: {info.get('modified') or 0}",
           f"Nube: {'conectada' if info.get('cloud') else 'no'}",
           f"Backups: {info.get('backups') or 0}",
           "",
           "Últimos errores:"]
    out += [f"  {e}" for e in errs] or ["  (ninguno)"]
    out += ["", f"Registro de la sesión ({len(log_lines)} líneas):"]
    out += [f"  {line}" for line in log_lines] or ["  (vacío)"]
    return "\n".join(out) + "\n"


def issue_url(text: str) -> str:
    """Link that opens a new issue in the public repository with the template and the report; long
    reports are cut (the full one is copied to the clipboard by the apps)."""
    text = text.strip()
    if len(text) > ISSUE_CHARS:
        text = text[:ISSUE_CHARS] + "\n…"
    body = ("**Qué pasó:**\n\n\n**Qué esperabas que pasara:**\n\n\n**Pasos para repetirlo:**\n1. \n\n"
            "**Diagnóstico** (generado por la app; sin nombres de presets ni datos personales):\n```\n" + text + "\n```\n")
    return (f"https://github.com/{RELEASES_REPO}/issues/new?title={quote('Problema: ', safe=URL_SAFE)}"
            f"&body={quote(body, safe=URL_SAFE)}")

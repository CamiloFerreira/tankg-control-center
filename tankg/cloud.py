"""Google Drive sync of the presets: the bank (36 presets), the preset/bank names and a history of
versions, so Linux, Windows and Android share one setup. Standard library only (urllib).

Sign-in, scope drive.appdata (the app only sees its own hidden folder in the user's Drive):
Windows/Linux open the browser and get the answer on a loopback address (one click, PKCE);
the APK uses the device flow (google.com/device + a code). android/ui/js/cloud.js implements
the same Drive protocol and file format.

Files in appDataFolder:
    tankg-cloud.json              latest version
    tankg-history-<stamp>.json    previous versions (newest HISTORY_KEEP are kept)
Both hold {"format": "tankg-cloud", "version": 1, "updated": ISO time (UTC), "device": "...",
"bank": hex of the 758-byte bank, "aliases": {"presets": {...}, "banks": {...}}}.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import platform
import secrets
import socket
import time
import webbrowser
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .cloud_config import DESKTOP_CLIENT_ID as CLIENT_ID, DESKTOP_CLIENT_SECRET as CLIENT_SECRET
from .model import Bank

SCOPE = "https://www.googleapis.com/auth/drive.appdata"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FILES = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
LATEST = "tankg-cloud.json"
HISTORY_PREFIX = "tankg-history-"
HISTORY_KEEP = 30
FORMAT = "tankg-cloud"


class CloudError(Exception):
    """Error with a message meant for the user."""


def configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def device_name() -> str:
    system = {"Linux": "Linux", "Windows": "Windows", "Darwin": "macOS"}.get(platform.system(), platform.system())
    return f"{system} · {socket.gethostname()}"


def _request(method: str, url: str, data: bytes | None = None, headers: dict | None = None,
             timeout: float = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CloudError(f"Sin conexión con Google ({e}). ¿Hay internet?") from e


def _form(url: str, fields: dict) -> tuple[int, dict]:
    status, body = _request("POST", url, urllib.parse.urlencode(fields).encode(),
                            {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return status, json.loads(body or b"{}")
    except ValueError:
        return status, {}


# sign-in ----------------------------------------------------------------------------------------

def sign_in_browser(open_url=webbrowser.open, should_stop=lambda: False, timeout: float = 300) -> str:
    """One-click sign-in for desktops: opens Google in the browser and receives the answer on
    http://127.0.0.1:<port>/. Returns the refresh token to store."""
    if not configured():
        raise CloudError("La sincronización con Google Drive no está configurada en esta versión.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if query.get("state") == state:
                result.update(query)
            ok = "code" in query and query.get("state") == state
            page = ("<h2>Listo: Tank-G Control Center ya puede sincronizar.</h2><p>Puedes cerrar esta pestaña.</p>" if ok
                    else "<h2>No se pudo conectar con Google Drive.</h2><p>Vuelve a la app e inténtalo de nuevo.</p>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body style='font-family:sans-serif;text-align:center;margin-top:15%'>{page}</body></html>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 0.5
    redirect = f"http://127.0.0.1:{server.server_port}/"
    open_url(f"{AUTH_URL}?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent"}))
    deadline = time.monotonic() + timeout
    try:
        while not result and time.monotonic() < deadline:
            if should_stop():
                raise CloudError("Inicio de sesión cancelado.")
            server.handle_request()
    finally:
        server.server_close()
    if not result:
        raise CloudError("No llegó la respuesta de Google: vuelve a intentarlo.")
    if "code" not in result:
        raise CloudError("Acceso denegado en Google." if result.get("error") == "access_denied"
                         else f"Google respondió: {result.get('error', 'error desconocido')}")
    status, doc = _form(TOKEN_URL, {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": result["code"],
                                    "code_verifier": verifier, "redirect_uri": redirect,
                                    "grant_type": "authorization_code"})
    if status != 200 or not doc.get("refresh_token"):
        raise CloudError(f"No se pudo iniciar sesión: {doc.get('error_description') or doc.get('error') or status}")
    return doc["refresh_token"]


class Drive:
    """Access to the app folder with a stored refresh token."""

    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token
        self._access = ""
        self._expires = 0.0

    def _token(self) -> str:
        if self._access and time.monotonic() < self._expires - 60:
            return self._access
        status, doc = _form(TOKEN_URL, {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                                        "refresh_token": self.refresh_token, "grant_type": "refresh_token"})
        if status != 200:
            raise CloudError("La sesión de Google caducó o fue revocada: vuelve a conectar con Google Drive.")
        self._access = doc["access_token"]
        self._expires = time.monotonic() + int(doc.get("expires_in", 3600))
        return self._access

    def _call(self, method: str, url: str, data: bytes | None = None, ctype: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if ctype:
            headers["Content-Type"] = ctype
        status, body = _request(method, url, data, headers)
        if status >= 400:
            try:
                msg = json.loads(body)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = str(status)
            raise CloudError(f"Google Drive respondió: {msg}")
        return json.loads(body) if body else {}

    def list(self) -> list[dict]:
        q = urllib.parse.urlencode({"spaces": "appDataFolder", "pageSize": 200,
                                    "fields": "files(id,name,modifiedTime)", "orderBy": "name desc"})
        return self._call("GET", f"{FILES}?{q}").get("files", [])

    def read(self, file_id: str) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}"}
        status, body = _request("GET", f"{FILES}/{file_id}?alt=media", None, headers)
        if status >= 400:
            raise CloudError(f"No se pudo leer de Google Drive ({status}).")
        return json.loads(body)

    def write(self, name: str, doc: dict, file_id: str | None = None) -> None:
        payload = json.dumps(doc, ensure_ascii=False).encode()
        if file_id:
            self._call("PATCH", f"{UPLOAD}/{file_id}?uploadType=media", payload, "application/json")
            return
        boundary = "tankg-boundary"
        meta = json.dumps({"name": name, "parents": ["appDataFolder"]}).encode()
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() + meta +
                f"\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode() + payload +
                f"\r\n--{boundary}--".encode())
        self._call("POST", f"{UPLOAD}?uploadType=multipart", body, f"multipart/related; boundary={boundary}")

    def delete(self, file_id: str) -> None:
        self._call("DELETE", f"{FILES}/{file_id}")


# sync -------------------------------------------------------------------------------------------

def make_doc(bank: Bank, presets: dict, banks: dict, device: str | None = None) -> dict:
    return {"format": FORMAT, "version": 1, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "device": device or device_name(), "bank": bank.to_bytes().hex(),
            "aliases": {"presets": dict(presets), "banks": dict(banks)}}


def doc_key(doc: dict) -> str:
    """Identity of a cloud version by content (presets and names), independent of its time."""
    blob = json.dumps({"bank": doc.get("bank"), "aliases": doc.get("aliases")}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def parse_doc(doc: dict) -> tuple[Bank, dict, dict]:
    if doc.get("format") != FORMAT:
        raise CloudError("El archivo de la nube no es de Tank-G Control Center.")
    bank = Bank.from_bytes(bytes.fromhex(doc["bank"]))
    aliases = doc.get("aliases") or {}
    return bank, dict(aliases.get("presets") or {}), dict(aliases.get("banks") or {})


def push(drive: Drive, doc: dict) -> None:
    """Uploads `doc` as the latest version; the previous latest goes to the history."""
    files = drive.list()
    latest = next((f for f in files if f["name"] == LATEST), None)
    if latest:
        old = drive.read(latest["id"])
        if old.get("bank") == doc["bank"] and old.get("aliases") == doc["aliases"]:
            return   # nothing changed
        stamp = old.get("updated", "").replace(":", "").replace("-", "")[:15] or time.strftime("%Y%m%dT%H%M%S")
        drive.write(f"{HISTORY_PREFIX}{stamp}.json", old)
    drive.write(LATEST, doc, latest["id"] if latest else None)
    history = sorted((f for f in files if f["name"].startswith(HISTORY_PREFIX)), key=lambda f: f["name"], reverse=True)
    for f in history[HISTORY_KEEP - 1:]:
        drive.delete(f["id"])


def pull(drive: Drive) -> dict | None:
    latest = next((f for f in drive.list() if f["name"] == LATEST), None)
    return drive.read(latest["id"]) if latest else None


def history(drive: Drive) -> list[dict]:
    """[{id, name, updated}]: the latest version first, then the history newest first."""
    files = drive.list()
    latest = [f for f in files if f["name"] == LATEST]
    older = sorted((f for f in files if f["name"].startswith(HISTORY_PREFIX)), key=lambda f: f["name"], reverse=True)
    return [{"id": f["id"], "name": f["name"], "updated": f.get("modifiedTime", "")} for f in latest + older]

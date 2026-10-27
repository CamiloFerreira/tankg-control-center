"""Google Drive sync of the presets: the bank (36 presets), the preset/bank names and a history of
versions, so Linux, Windows and Android share one setup. Standard library only (urllib).

Sign-in with Google's device flow on every platform (one OAuth client of type "TVs and Limited
Input devices"): the app shows a code, opens google.com/device and polls until the user allows it.
Scope drive.file (the app only sees the files it created: a "Tank-G Control Center" folder in the
user's Drive; it is the only Drive scope Google allows for the device flow).
android/ui/js/cloud.js implements the same sign-in, Drive protocol and file format.

Files in the "Tank-G Control Center" folder:
    tankg-cloud.json              latest version
    tankg-history-<stamp>.json    previous versions (newest HISTORY_KEEP are kept)
Both hold {"format": "tankg-cloud", "version": 1, "updated": ISO time (UTC), "device": "...",
"bank": hex of the 758-byte bank, "aliases": {"presets": {...}, "banks": {...}}}.
"""
from __future__ import annotations

import hashlib
import json
import platform
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .cloud_config import CLIENT_ID, CLIENT_SECRET
from .model import Bank

SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER = "Tank-G Control Center"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
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

def start_sign_in() -> dict:
    """Asks Google for a sign-in code: {"device_code", "user_code", "url", "interval", "expires_in"}."""
    if not configured():
        raise CloudError("La sincronización con Google Drive no está configurada en esta versión.")
    status, doc = _form(DEVICE_URL, {"client_id": CLIENT_ID, "scope": SCOPE})
    if status != 200:
        raise CloudError(f"Google rechazó el inicio de sesión: {doc.get('error_description') or doc.get('error') or status}")
    return {"device_code": doc["device_code"], "user_code": doc["user_code"],
            "url": doc.get("verification_url") or doc.get("verification_uri"),
            "interval": int(doc.get("interval", 5)), "expires_in": int(doc.get("expires_in", 1800))}


def finish_sign_in(code: dict, should_stop=lambda: False) -> str:
    """Waits until the user enters the code and allows access. Returns the refresh token to store."""
    deadline = time.monotonic() + code["expires_in"]
    interval = code["interval"]
    while time.monotonic() < deadline:
        for _ in range(interval * 10):   # sleep in small steps so a cancel is quick
            if should_stop():
                raise CloudError("Inicio de sesión cancelado.")
            time.sleep(0.1)
        status, doc = _form(TOKEN_URL, {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                                        "device_code": code["device_code"],
                                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if status == 200 and doc.get("refresh_token"):
            return doc["refresh_token"]
        if doc.get("error") == "authorization_pending":
            continue
        if doc.get("error") == "slow_down":
            interval += 5
            continue
        if doc.get("error") == "access_denied":
            raise CloudError("Acceso denegado en Google.")
        raise CloudError(f"No se pudo iniciar sesión: {doc.get('error_description') or doc.get('error') or status}")
    raise CloudError("El código caducó: vuelve a intentarlo.")


class Drive:
    """Access to the app folder with a stored refresh token."""

    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token
        self._access = ""
        self._expires = 0.0
        self._folder = ""

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

    def _query(self, q: str) -> list[dict]:
        params = urllib.parse.urlencode({"q": q, "pageSize": 200, "fields": "files(id,name,modifiedTime)",
                                         "orderBy": "name desc"})
        return self._call("GET", f"{FILES}?{params}").get("files", [])

    def folder(self) -> str:
        """Id of the app's folder, created on first use."""
        if not self._folder:
            found = self._query(f"name = '{FOLDER}' and mimeType = '{FOLDER_MIME}' and trashed = false")
            if found:
                self._folder = found[0]["id"]
            else:
                meta = json.dumps({"name": FOLDER, "mimeType": FOLDER_MIME}).encode()
                self._folder = self._call("POST", f"{FILES}?fields=id", meta, "application/json")["id"]
        return self._folder

    def list(self) -> list[dict]:
        return self._query(f"'{self.folder()}' in parents and trashed = false")

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
        meta = json.dumps({"name": name, "parents": [self.folder()]}).encode()
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

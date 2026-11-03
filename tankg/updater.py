"""Self-update of the desktop executables from the public releases repository
(tankg.version.RELEASES_REPO). The APK does the same through android/ui/js/app.js + MainActivity.

Only the PyInstaller builds replace themselves; running from source just reports the new
version. The Debian package (packaging/build_deb.sh, /opt/tankg/TankG owned by root) updates by
downloading the new .deb and installing it with pkexec + apt-get. Every download is checked against the release's SHA256SUMS before it is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .version import RELEASES_REPO, __version__

API = f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest"
PAGE = f"https://github.com/{RELEASES_REPO}/releases/latest"
ASSETS = {"win32": "TankG-windows-x64.exe", "linux": "TankG-linux-x86_64"}
DEB_ASSET = "TankG-linux-amd64.deb"
DEB_DIR = Path("/opt/tankg")


def installed_from_deb(exe: str | None = None) -> bool:
    return sys.platform == "linux" and Path(exe or sys.executable).resolve().parent == DEB_DIR


ASSET = DEB_ASSET if getattr(sys, "frozen", False) and installed_from_deb() else ASSETS.get(sys.platform)


class UpdateError(Exception):
    """Error with a message meant for the user."""


@dataclass
class Release:
    version: str
    notes: str
    asset_url: str | None
    sums_url: str | None
    min_version: str = ""   # versions older than this must update before the app can be used


MIN_MARK = re.compile(r"<!--\s*tankg-min-version:\s*v?([0-9]+(?:\.[0-9]+){0,2})\s*-->")


def min_version(body: str) -> str:
    """The minimum version declared by a release (<!-- tankg-min-version: 1.11.0 -->), or ""."""
    m = MIN_MARK.search(body or "")
    return m.group(1) if m else ""


def required(rel: Release, current: str = __version__) -> bool:
    """This version is no longer allowed: the update is mandatory (security fixes)."""
    return bool(rel.min_version) and newer(rel.version, current) and newer(rel.min_version, current)


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in v.lstrip("v").split(".")[:3])


def newer(candidate: str, current: str = __version__) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def _get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "tankg-updater", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Todavía no hay versiones publicadas.") from e
        raise UpdateError(f"El servidor de actualizaciones respondió con el error {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"No se pudo consultar las actualizaciones ({e}). ¿Hay internet?") from e


def latest() -> Release:
    doc = json.loads(_get(API))
    assets = {a["name"]: a["browser_download_url"] for a in doc.get("assets", [])}
    body = str(doc.get("body") or "")
    notes = MIN_MARK.sub("", body).split("\n## Verificar")[0].strip()
    return Release(str(doc.get("tag_name", "")).lstrip("v"), notes, assets.get(ASSET or ""), assets.get("SHA256SUMS"),
                   min_version(body))


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False) and ASSET)


def expected_sha256(sums: str, name: str) -> str | None:
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    return None


def download(rel: Release, progress=None) -> bytes:
    """The new executable, verified against SHA256SUMS."""
    if not rel.asset_url or not rel.sums_url:
        raise UpdateError("Esta versión no trae el ejecutable para tu sistema.")
    if progress:
        progress("Descargando…")
    data = _get(rel.asset_url, timeout=300)
    want = expected_sha256(_get(rel.sums_url).decode("utf-8", "replace"), ASSET)
    if not want or hashlib.sha256(data).hexdigest() != want:
        raise UpdateError("La descarga no coincide con SHA256SUMS: no se instala.")
    return data


def install(data: bytes) -> None:
    """Replace the running executable and start the new one. The caller quits right after."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "win32":
        # A running .exe cannot be overwritten: a small script waits for us to exit, swaps and relaunches.
        new = exe.with_name(exe.stem + ".new.exe")
        new.write_bytes(data)
        script = Path(tempfile.mkdtemp(prefix="tankg-update-")) / "tankg-update.cmd"   # private folder
        script.write_text(
            "@echo off\r\n:wait\r\ntimeout /t 1 /nobreak >nul\r\n"
            f'move /y "{new}" "{exe}" >nul 2>&1 || goto wait\r\n'
            f'start "" "{exe}"\r\ndel "%~f0"\r\n', encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000 | 0x00000008,   # no window, detached
                         close_fds=True)
    elif installed_from_deb(str(exe)):
        # Root-owned: apt installs the new package (pkexec asks for the password), then we restart.
        # The verified .deb goes into a new folder only we can write (mkdtemp, 0700; apt reads it as
        # root): a fixed name in /tmp would let another local user swap the package before apt runs.
        folder = Path(tempfile.mkdtemp(prefix="tankg-update-"))
        folder.chmod(0o711)   # apt's unprivileged downloader only needs to reach the file
        deb = folder / DEB_ASSET
        with open(deb, "xb") as f:
            f.write(data)
        deb.chmod(0o644)
        if shutil.which("pkexec") and shutil.which("apt-get"):
            subprocess.Popen(["sh", "-c", 'pkexec apt-get install -y "$1"; rm -rf "$2"; exec "$3"', "tankg-update",
                              str(deb), str(folder), str(exe)], start_new_session=True, close_fds=True)
        else:
            subprocess.Popen(["xdg-open", str(deb)], start_new_session=True, close_fds=True)
    else:
        tmp = exe.with_name(exe.name + ".new")
        tmp.unlink(missing_ok=True)
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700), "wb") as f:   # never through a symlink
            f.write(data)
        tmp.chmod(0o755)
        os.replace(tmp, exe)   # the running process keeps the old inode; the new file is used from now on
        subprocess.Popen([str(exe), *sys.argv[1:]], start_new_session=True, close_fds=True)

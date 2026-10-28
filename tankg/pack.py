"""Preset packs (.tgpack): presets (one, a bank of 4 or all 36) with their names, plus the AMP models
(.am4data) they use and the TYPE slot each model was in. Importing one uploads the models and then the
presets; a model can go to another slot, and the presets that use it follow (remap).
android/ui/js/files.js reads and writes the same format (tests check both ways).

    {"format": "tankg-pack", "version": 1, "title": "...",
     "presets": [{"slot": "3A", "name": "...", "raw": "<21 bytes hex>"}, ...],
     "banks": {"3": "bank name"},                       # names of the banks included whole
     "amps": [{"slot": 2, "name": "RANDALL Clean", "data": "<.am4data base64>"}, ...]}   # slot 1-9

Instead of "data", an AMP can be a reference to the public M-VAVE community catalog,
{"community": {"article": 7414, "file": "<file name>"}, "credit": {...}}: the band packs shipped
with the apps (packs/, BAND_PACKS) are like that, so the apps never redistribute third-party
captures; the model is downloaded from its original publication when the pack is imported.
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import am4
from .model import AMP_MODELS, OFF_AMP, Bank, Preset, parse_slot, slot_name

FORMAT = "tankg-pack"
EXTENSION = ".tgpack"
COMMUNITY_DOWNLOAD = "https://community.m-vave.com/bbs/api/download"
# band packs shipped with the app (references only; unpacked under sys._MEIPASS in a PyInstaller build)
BUILTIN_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "packs"


@dataclass
class PackAmp:
    slot: int          # 0-8: the TYPE it replaces
    name: str
    data: bytes | None                 # the .am4data (with or without its LMT block), or None:
    community: dict | None = None      # {"article", "file"}: download it from the M-VAVE community
    credit: dict | None = None         # {"author", "title", "source", "original"}

    def credit_text(self) -> str:
        c = self.credit or {}
        return f"«{c.get('title', self.name)}» de {c['author']} ({c.get('source', '')})" if c.get("author") else ""


@dataclass
class Pack:
    title: str | None
    presets: list[tuple[int, Preset, str | None]]          # (original slot 0-35, preset, name)
    amps: list[PackAmp] = field(default_factory=list)
    banks: dict[str, str] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return {1: "preset", 4: "bank", 36: "all"}.get(len(self.presets), "set")


def make(bank: Bank, slots: list[int], preset_names: dict[int, str], bank_names: dict[str, str],
         amp_names: dict[str, str], models: dict[int, bytes], title: str | None = None) -> tuple[dict, list[int]]:
    """The pack document for `slots` and the uploaded AMP slots used by them whose model file this
    device doesn't have (they are left out)."""
    used = sorted({bank.presets[s].amp for s in slots})
    custom = [a for a in used if amp_names.get(str(a + 1))]
    whole = {s // 4 for s in slots if all(b in slots for b in range(s // 4 * 4, s // 4 * 4 + 4))}
    doc = {
        "format": FORMAT, "version": 1, "title": title or None,
        "presets": [{"slot": slot_name(s), "name": preset_names.get(s) or None, "raw": bank.presets[s].to_bytes().hex()}
                    for s in slots],
        "banks": {str(b + 1): bank_names[str(b + 1)] for b in sorted(whole) if bank_names.get(str(b + 1))},
        "amps": [{"slot": a + 1, "name": amp_names[str(a + 1)], "data": base64.b64encode(models[a]).decode()}
                 for a in custom if a in models],
    }
    return doc, [a for a in custom if a not in models]


def parse(doc: dict) -> Pack:
    if doc.get("format") != FORMAT:
        raise ValueError("No es un pack de Tank-G (.tgpack).")
    presets = []
    for it in doc.get("presets") or []:
        raw = bytes.fromhex(str(it.get("raw", "")))
        if len(raw) != 21:
            raise ValueError("Algún preset del pack no tiene 21 bytes.")
        presets.append((parse_slot(str(it.get("slot", "1A"))), Preset(bytearray(raw)), it.get("name") or None))
    if not presets:
        raise ValueError("El pack no contiene presets.")
    amps = []
    for it in doc.get("amps") or []:
        slot = int(it.get("slot", 0)) - 1
        if not 0 <= slot < len(AMP_MODELS):
            raise ValueError("Un modelo de AMP del pack tiene un espacio inválido.")
        ref = it.get("community")
        if ref and not it.get("data"):
            if not (isinstance(ref, dict) and int(ref.get("article", 0)) > 0 and ref.get("file")):
                raise ValueError("Un modelo de AMP del pack tiene una referencia inválida.")
            data, ref = None, {"article": int(ref["article"]), "file": str(ref["file"])}
        else:
            data, ref = base64.b64decode(str(it.get("data", ""))), None
            am4.check(data)
        amps.append(PackAmp(slot, str(it.get("name") or f"AMP {slot + 1}"), data, ref, it.get("credit") or None))
    return Pack(doc.get("title") or None, presets, amps, {str(k): str(v) for k, v in (doc.get("banks") or {}).items()})


def save(doc: dict, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def load(path: str | Path) -> Pack:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"{Path(path).name}: no es un archivo .tgpack válido") from e
    return parse(doc)


def _cache_path(ref: dict) -> Path:
    from .library import DATA_DIR
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in ref["file"])[-80:]
    return DATA_DIR / "community" / f"{ref['article']}_{safe}"


def cached(amp: PackAmp) -> bool:
    """The model is in the pack or already downloaded to this device."""
    return amp.data is not None or _cache_path(amp.community).exists()


def fetch(amp: PackAmp) -> bytes:
    """The model of an AMP: embedded, downloaded before (kept on this device) or downloaded now from
    its community publication."""
    if amp.data is not None:
        return amp.data
    path = _cache_path(amp.community)
    try:
        data = path.read_bytes()
        am4.check(data)
        return data
    except (OSError, ValueError):
        pass
    url = COMMUNITY_DOWNLOAD + "?" + urllib.parse.urlencode({"articleId": amp.community["article"], "file": amp.community["file"]})
    try:
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Tank-G Control Center"}),
                                      timeout=60).read()
    except OSError as e:
        raise ValueError(f"No se pudo descargar «{amp.name}» de la comunidad de M-VAVE ({e}). ¿Hay internet?") from e
    am4.check(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def missing(packs: list[Pack]) -> list[PackAmp]:
    """Referenced models of these packs not downloaded yet (each model once)."""
    seen, out = set(), []
    for p in packs:
        for amp in p.amps:
            if amp.data is None and not cached(amp) and (key := (amp.community["article"], amp.community["file"])) not in seen:
                seen.add(key)
                out.append(amp)
    return out


def builtin() -> list[tuple[Path, Pack]]:
    """The band packs shipped with the app (packs/*.tgpack)."""
    out = []
    for path in sorted(BUILTIN_DIR.glob(f"*{EXTENSION}")):
        try:
            out.append((path, load(path)))
        except (OSError, ValueError):
            continue
    return out


def remap(presets: list[Preset], moves: dict[int, int]) -> list[Preset]:
    """Copies of the presets with the TYPE of moved models changed ({old slot: new slot}, 0-8)."""
    out = []
    for p in presets:
        q = p.copy()
        if q.raw[OFF_AMP] in moves:
            q.raw[OFF_AMP] = moves[q.raw[OFF_AMP]]
        out.append(q)
    return out

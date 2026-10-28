"""Local files: bank images, single-preset files, automatic backups, factory bank.

.tgbank   raw 758-byte bank image, same layout as the pedal and as M-EFCS's
          tankG_*_preset.bin assets (those load directly too).
.tgpreset JSON with the 21 raw bytes in hex plus readable fields (informative only;
          on import only "raw" is used).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .model import Bank, Preset, slot_name

PRESET_FORMAT = "tankg-preset"
# In a PyInstaller build bundled data files are unpacked under sys._MEIPASS.
PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
if os.name == "nt":
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "tankg"
else:
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "tankg"
BACKUP_DIR = DATA_DIR / "backups"
ALIAS_FILE = DATA_DIR / "aliases.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
FACTORY_DIR = PROJECT_ROOT / "research/factory"
# Factory sets: 36 presets + the AMP/CAB models image. "original" is the pedal as it comes out of the
# box (M-EFCS "factory" restore read back from the pedal on 2026-10-28: the AM3 presets, 9D's LED as the
# pedal keeps it) and is the default; "am4"/"am3" are the two sets inside M-EFCS.
FACTORY_SETS = {"original": "Original (de caja)", "am4": "AM4 (modelos nuevos)", "am3": "AM3"}
FACTORY_AMPCAB = {"original": "am3", "am4": "am4", "am3": "am3"}   # AMP/CAB image of each set (original: inferred)
FACTORY_NAMES = {"original": "original", "am3": "original"}         # names file of each set (same presets)
DEFAULT_FACTORY_SET = "original"
FACTORY_CANDIDATES = [
    DATA_DIR / "factory.tgbank",
    FACTORY_DIR / "tankG_am4_preset.bin",
]


def _read_json(path: str | Path):
    """JSON files are UTF-8 on every platform (they travel between Windows, Linux and Android).
    Files written by older Windows builds used the ANSI code page: read those as a fallback."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return json.loads(text)


def _write_json(path: Path, doc, ascii_only: bool = False) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=ascii_only) + "\n", encoding="utf-8")


def load_bank(path: str | Path) -> Bank:
    return Bank.from_bytes(Path(path).read_bytes())


def save_bank(bank: Bank, path: str | Path) -> Path:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(bank.to_bytes())
    tmp.replace(path)
    return path


def save_preset(preset: Preset, path: str | Path, source_slot: int | None = None,
                name: str | None = None) -> Path:
    doc = {
        "format": PRESET_FORMAT,
        "version": 1,
        "name": name,
        "raw": preset.to_bytes().hex(),
        "amp": preset.amp_name,
        "cab": preset.cab_name,
        "source_slot": slot_name(source_slot) if source_slot is not None else None,
        "saved": datetime.now().isoformat(timespec="seconds"),
    }
    path = Path(path)
    _write_json(path, doc, ascii_only=True)
    return path


def load_preset(path: str | Path) -> Preset:
    return load_preset_file(path)[0]


def load_preset_file(path: str | Path) -> tuple[Preset, str | None]:
    """The preset and its interface name (None if the file has none)."""
    try:
        doc = _read_json(path)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: no es un archivo .tgpreset válido") from e
    if doc.get("format") != PRESET_FORMAT:
        raise ValueError(f"{path}: formato desconocido {doc.get('format')!r}")
    return Preset.from_hex(doc["raw"]), doc.get("name") or None


def backup(bank: Bank, reason: str = "manual") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"bank-{stamp}-{reason}.tgbank"
    n = 1
    while path.exists():
        path = BACKUP_DIR / f"bank-{stamp}-{reason}-{n}.tgbank"
        n += 1
    return save_bank(bank, path)


def list_backups() -> list[Path]:
    return sorted(BACKUP_DIR.glob("*.tgbank"), reverse=True) if BACKUP_DIR.exists() else []


def factory_bank(kind: str | None = None) -> Bank | None:
    """Factory presets of `kind` (FACTORY_SETS; default: the set last restored, see Settings)."""
    kind = kind or Settings().factory_set
    for p in FACTORY_CANDIDATES if kind == "am4" else [FACTORY_DIR / f"tankG_{kind}_preset.bin"]:
        if p.exists():
            try:
                return load_bank(p)
            except ValueError:
                continue
    return None


def factory_ampcab(kind: str) -> bytes | None:
    """Factory image of the 9 AMP and 8 CAB models (212992 bytes) of set `kind`."""
    try:
        data = (FACTORY_DIR / f"tankG_{FACTORY_AMPCAB.get(kind, kind)}_ampCab.bin").read_bytes()
    except OSError:
        return None
    return data if len(data) == 0x34000 else None


def factory_names(kind: str | None = None) -> dict:
    """{"banks": {"1": name}, "presets": {"1A": name}} of a factory set (empty when it has none)."""
    kind = kind or Settings().factory_set
    try:
        doc = _read_json(FACTORY_DIR / f"tankG_{FACTORY_NAMES[kind]}_names.json")
    except (KeyError, OSError, ValueError):
        return {"banks": {}, "presets": {}}
    return {"banks": dict(doc.get("banks") or {}), "presets": dict(doc.get("presets") or {})}


class ModelStore:
    """Copies of the AMP models (.am4data) uploaded to the pedal, one per TYPE slot, so a pack can
    include them (the pedal can't be read back). Only on this device; cleared by a factory restore."""

    def __init__(self, folder: Path | None = None):
        self.folder = folder or DATA_DIR / "amps"

    def _path(self, slot: int) -> Path:
        return self.folder / f"amp{slot + 1}.am4data"

    def get(self, slot: int) -> bytes | None:
        try:
            return self._path(slot).read_bytes()
        except OSError:
            return None

    def all(self) -> dict[int, bytes]:
        return {s: d for s in range(9) if (d := self.get(s)) is not None}

    def put(self, slot: int, data: bytes) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self._path(slot).write_bytes(data)

    def clear(self) -> None:
        for s in range(9):
            self._path(s).unlink(missing_ok=True)


class Aliases:
    """Interface-only names for presets ("6A"), banks ("6") and uploaded AMP models ("3");
    the pedal has no names."""

    def __init__(self, path: Path = ALIAS_FILE):
        self.path = path
        self.presets: dict[str, str] = {}
        self.banks: dict[str, str] = {}
        self.amps: dict[str, str] = {}
        self.amp_sources: dict[str, dict] = {}   # slot -> {"article", "file"}: the community model it came from
        self.preset_amps: dict[str, dict] = {}   # "9A" -> {"slot", "name", "source"}: the model a pack preset needs
        try:
            doc = _read_json(path)
            self.presets = {k: v for k, v in doc.get("presets", {}).items() if v}
            self.banks = {k: v for k, v in doc.get("banks", {}).items() if v}
            self.amps = {k: v for k, v in doc.get("amps", {}).items() if v}
            self.amp_sources = {k: v for k, v in doc.get("amp_sources", {}).items() if v}
            self.preset_amps = {k: v for k, v in doc.get("preset_amps", {}).items() if v}
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        _write_json(tmp, {"presets": self.presets, "banks": self.banks, "amps": self.amps, "amp_sources": self.amp_sources,
                          "preset_amps": self.preset_amps})
        tmp.replace(self.path)

    def preset(self, slot: int) -> str:
        return self.presets.get(slot_name(slot), "")

    def set_preset(self, slot: int, name: str) -> None:
        name = name.strip()
        if name:
            self.presets[slot_name(slot)] = name
        else:
            self.presets.pop(slot_name(slot), None)
        self.save()

    def bank(self, bank: int) -> str:
        """bank: 0-based."""
        return self.banks.get(str(bank + 1), "")

    def set_bank(self, bank: int, name: str) -> None:
        name = name.strip()
        if name:
            self.banks[str(bank + 1)] = name
        else:
            self.banks.pop(str(bank + 1), None)
        self.save()

    def amp(self, slot: int) -> str:
        """Name of the model uploaded to AMP slot `slot` (0-8); empty = factory model."""
        return self.amps.get(str(slot + 1), "")

    def set_amp(self, slot: int, name: str, source: dict | None = None) -> None:
        """`source`: the community publication of the model ({"article", "file"}), so another device
        synced through the cloud can download it; None for a model from a file."""
        name = name.strip()
        if name:
            self.amps[str(slot + 1)] = name
        else:
            self.amps.pop(str(slot + 1), None)
        if name and source:
            self.amp_sources[str(slot + 1)] = {"article": int(source["article"]), "file": str(source["file"])}
        else:
            self.amp_sources.pop(str(slot + 1), None)
        self.save()

    def set_preset_amp(self, slot: int, need: dict | None) -> None:
        """The uploaded model a preset was made for ({"slot", "name", "source"}), or None."""
        if need:
            self.preset_amps[slot_name(slot)] = need
        else:
            self.preset_amps.pop(slot_name(slot), None)
        self.save()

    def missing_amp(self, slot: int, preset: Preset) -> dict | None:
        """The model a preset needs when its TYPE now holds something else on the pedal (None = fine)."""
        need = self.preset_amps.get(slot_name(slot))
        if need and preset.amp == need["slot"] and self.amp(need["slot"]) != need["name"]:
            return need
        return None

    def swap(self, a: int, b: int) -> None:
        na, nb = self.preset(a), self.preset(b)
        self.presets.pop(slot_name(a), None)
        self.presets.pop(slot_name(b), None)
        if nb:
            self.presets[slot_name(a)] = nb
        if na:
            self.presets[slot_name(b)] = na
        self.save()


SET_FORMAT = "tankg-set"


def save_set(bank: Bank, slots: list[int], path: str | Path, aliases: "Aliases | None" = None,
             title: str | None = None) -> Path:
    """Several presets with their names, e.g. one bank of 4 to share."""
    doc = {
        "format": SET_FORMAT,
        "version": 1,
        "title": title,
        "presets": [
            {"slot": slot_name(s), "name": (aliases.preset(s) if aliases else "") or None,
             "raw": bank.presets[s].to_bytes().hex()}
            for s in slots
        ],
    }
    path = Path(path)
    _write_json(path, doc)
    return path


def load_set(path: str | Path) -> tuple[str | None, list[tuple[Preset, str | None]]]:
    try:
        doc = _read_json(path)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: no es un archivo .tgset válido") from e
    if doc.get("format") != SET_FORMAT:
        raise ValueError(f"{path}: formato desconocido {doc.get('format')!r}")
    items = [(Preset.from_hex(it["raw"]), it.get("name") or None) for it in doc.get("presets", [])]
    if not items:
        raise ValueError(f"{path}: no contiene presets")
    return doc.get("title") or None, items


class Settings:
    """Small persistent app settings (currently the manually chosen MIDI ports)."""

    def __init__(self, path: Path | None = None):
        self.path = path or SETTINGS_FILE
        self.data: dict = {}
        try:
            self.data = _read_json(self.path)
        except (OSError, ValueError):
            pass

    @property
    def midi_ports(self) -> tuple[str, str] | None:
        """(input name, output name) chosen by the user, or None for automatic detection."""
        i, o = self.data.get("midi_in"), self.data.get("midi_out")
        return (i, o) if i and o else None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(self.path, self.data)

    @property
    def ai(self) -> dict:
        """{"provider", "model", "base_url", "keys": {provider: api key}} (keys only if remembered)."""
        return self.data.get("ai", {})

    def set_ai(self, ai: dict) -> None:
        self.data["ai"] = ai
        self.save()

    @property
    def factory_set(self) -> str:
        """Factory set last restored on the pedal (default: as it comes out of the box); the editor's
        factory presets follow it."""
        kind = self.data.get("factory_set")
        return kind if kind in FACTORY_SETS else DEFAULT_FACTORY_SET

    def set_factory_set(self, kind: str) -> None:
        self.data["factory_set"] = kind
        self.save()

    @property
    def ble(self) -> tuple[str, str] | None:
        """(name, address) of the Bluetooth pedal chosen in "Puerto MIDI…", or None."""
        b = self.data.get("ble") or {}
        return (b["name"], b["address"]) if b.get("address") else None

    def set_ble(self, device: tuple[str, str] | None) -> None:
        if device:
            self.data["ble"] = {"name": device[0], "address": device[1]}
        else:
            self.data.pop("ble", None)
        self.save()

    @property
    def cloud(self) -> dict:
        """{"refresh_token", "synced": "updated" of the cloud version this device last matched}."""
        return self.data.get("cloud", {})

    def set_cloud(self, cloud: dict | None) -> None:
        if cloud:
            self.data["cloud"] = cloud
        else:
            self.data.pop("cloud", None)
        self.save()

    def set_midi_ports(self, ports: tuple[str, str] | None) -> None:
        if ports:
            self.data["midi_in"], self.data["midi_out"] = ports
        else:
            self.data.pop("midi_in", None)
            self.data.pop("midi_out", None)
        self.save()

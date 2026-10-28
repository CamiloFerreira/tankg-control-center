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
# The two factory sets of M-EFCS ("AM4" newer models, "AM3"): 36 presets + the AMP/CAB models image.
FACTORY_SETS = {"am4": "AM4", "am3": "AM3"}
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
    """Factory presets of `kind` ("am4"/"am3"; default: the set last restored, see Settings)."""
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
        data = (FACTORY_DIR / f"tankG_{kind}_ampCab.bin").read_bytes()
    except OSError:
        return None
    return data if len(data) == 0x34000 else None


class Aliases:
    """Interface-only names for presets ("6A"), banks ("6") and uploaded AMP models ("3");
    the pedal has no names."""

    def __init__(self, path: Path = ALIAS_FILE):
        self.path = path
        self.presets: dict[str, str] = {}
        self.banks: dict[str, str] = {}
        self.amps: dict[str, str] = {}
        try:
            doc = _read_json(path)
            self.presets = {k: v for k, v in doc.get("presets", {}).items() if v}
            self.banks = {k: v for k, v in doc.get("banks", {}).items() if v}
            self.amps = {k: v for k, v in doc.get("amps", {}).items() if v}
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        _write_json(tmp, {"presets": self.presets, "banks": self.banks, "amps": self.amps})
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

    def set_amp(self, slot: int, name: str) -> None:
        name = name.strip()
        if name:
            self.amps[str(slot + 1)] = name
        else:
            self.amps.pop(str(slot + 1), None)
        self.save()

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
        """Factory set ("am4"/"am3") last restored on the pedal; the editor's factory presets follow it."""
        kind = self.data.get("factory_set")
        return kind if kind in FACTORY_SETS else "am4"

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

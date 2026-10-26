"""Local files: bank images, single-preset files, automatic backups, factory bank.

.tgbank   raw 758-byte bank image, same layout as the pedal and as M-EFCS's
          tankG_*_preset.bin assets (those load directly too).
.tgpreset JSON with the 21 raw bytes in hex plus readable fields (informative only;
          on import only "raw" is used).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .model import Bank, Preset, slot_name

PRESET_FORMAT = "tankg-preset"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if os.name == "nt":
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "tankg"
else:
    DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "tankg"
BACKUP_DIR = DATA_DIR / "backups"
ALIAS_FILE = DATA_DIR / "aliases.json"
FACTORY_CANDIDATES = [
    DATA_DIR / "factory.tgbank",
    PROJECT_ROOT / "research/factory/tankG_am4_preset.bin",
]


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
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def load_preset(path: str | Path) -> Preset:
    return load_preset_file(path)[0]


def load_preset_file(path: str | Path) -> tuple[Preset, str | None]:
    """The preset and its interface name (None if the file has none)."""
    try:
        doc = json.loads(Path(path).read_text())
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
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


def factory_bank() -> Bank | None:
    for p in FACTORY_CANDIDATES:
        if p.exists():
            try:
                return load_bank(p)
            except ValueError:
                continue
    return None


class Aliases:
    """Interface-only names for presets ("6A") and banks ("6"); the pedal has no names."""

    def __init__(self, path: Path = ALIAS_FILE):
        self.path = path
        self.presets: dict[str, str] = {}
        self.banks: dict[str, str] = {}
        try:
            doc = json.loads(path.read_text())
            self.presets = {k: v for k, v in doc.get("presets", {}).items() if v}
            self.banks = {k: v for k, v in doc.get("banks", {}).items() if v}
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"presets": self.presets, "banks": self.banks},
                                  indent=2, ensure_ascii=False) + "\n")
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

    def swap(self, a: int, b: int) -> None:
        na, nb = self.preset(a), self.preset(b)
        self.presets.pop(slot_name(a), None)
        self.presets.pop(slot_name(b), None)
        if nb:
            self.presets[slot_name(a)] = nb
        if na:
            self.presets[slot_name(b)] = na
        self.save()

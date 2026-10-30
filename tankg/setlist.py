"""Setlists: the songs of a show, saved with the preset names (Aliases.setlists, synced through the
cloud), played in stage mode (dialogs.StageWindow) and optionally put in footswitch order (1A, 1B,
1C, 1D, 2A…) from a starting slot, so on stage the next song is always the next preset. Same logic
in android/ui/js/setlist.js (checked against each other by tests/test_ui.py).

A song remembers its preset's slot, bytes and name: resolve() finds it again after presets move
(this setlist ordered, another one ordered, a swap…). Ordering swaps each song into its place, so
only the presets involved change slot; preset names and their AMP notes move with them.
"""
from __future__ import annotations

import re

from .model import AMP_MODELS, SLOTS, Bank, slot_name

_SLOT_RE = re.compile(r"[1-9][ABCD]")
_HEX_RE = re.compile(r"(?:[0-9a-fA-F]{2})*")


def song(bank: Bank, names: dict[str, str], slot: int, note: str = "") -> dict:
    """A setlist entry for the preset now in `slot`."""
    return {"slot": slot_name(slot), "raw": bank.presets[slot].to_bytes().hex(),
            "name": names.get(slot_name(slot), ""), "note": note}


def resolve(songs: list[dict], bank: Bank, names: dict[str, str]) -> list[int | None]:
    """Current slot of each song (None = no preset matches any more). Same bytes count most, then
    same name, then same slot; bytes or name must match. Each slot serves one song."""
    used: set[int] = set()
    out: list[int | None] = []
    for s in songs:
        best, best_score = None, 1
        for slot in range(SLOTS):
            if slot in used:
                continue
            score = (4 * (bank.presets[slot].to_bytes().hex() == s.get("raw"))
                     + 2 * bool(s.get("name") and names.get(slot_name(slot)) == s.get("name"))
                     + (slot_name(slot) == s.get("slot")))
            if score > best_score:
                best, best_score = slot, score
        if best is not None:
            used.add(best)
        out.append(best)
    return out


def refresh(songs: list[dict], bank: Bank, names: dict[str, str]) -> list[dict]:
    """The songs pointing to where their presets are now (unmatched ones are kept as they were)."""
    return [song(bank, names, slot, s.get("note", "")) if slot is not None else dict(s)
            for s, slot in zip(songs, resolve(songs, bank, names))]


def layout(order: list[int], start: int = 0) -> list[int]:
    """source[new slot] = old slot after placing `order` (old slots, no repeats) at start, start+1…"""
    if len(set(order)) != len(order) or any(not 0 <= s < SLOTS for s in order):
        raise ValueError("setlist con slots repetidos o fuera de rango")
    if start < 0 or start + len(order) > SLOTS:
        raise ValueError(f"no entran {len(order)} canciones desde {slot_name(min(max(start, 0), SLOTS - 1))}")
    source = list(range(SLOTS))
    for i, s in enumerate(order):
        j = source.index(s)
        source[start + i], source[j] = source[j], source[start + i]
    return source


def apply(bank: Bank, source: list[int]) -> Bank:
    return Bank([bank.presets[s].copy() for s in source])


def move_names(names: dict[str, object], source: list[int]) -> dict[str, object]:
    """Per-slot data keyed by slot name ("6A": …) after the move."""
    return {slot_name(new): names[slot_name(old)] for new, old in enumerate(source) if slot_name(old) in names}


def label(s: dict) -> str:
    """What the song is called: its preset name, else its AMP model (like the preset list)."""
    raw = s.get("raw") or ""
    amp = int(raw[10:12], 16) if len(raw) >= 12 else -1
    return s.get("name") or (AMP_MODELS[amp] if 0 <= amp < len(AMP_MODELS) else f"Preset {s.get('slot', '?')}")


def text(title: str, songs: list[dict], slots: list[int | None]) -> str:
    """The setlist to print or share: song number, slot to step on, name and note."""
    lines = [f"SETLIST · {title.strip()}" if title.strip() else "SETLIST", ""]
    for i, (s, slot) in enumerate(zip(songs, slots)):
        note = s.get("note", "").strip()
        lines.append(f"{i + 1:>2}. {slot_name(slot) if slot is not None else '--'}  {label(s)}" + (f"  ({note})" if note else ""))
    return "\n".join(lines) + "\n"


def clean(doc: object) -> list[dict]:
    """Setlists read from aliases.json or the cloud, keeping only well-formed entries."""
    out = []
    for sl in doc if isinstance(doc, list) else []:
        if not isinstance(sl, dict):
            continue
        songs = []
        for s in sl.get("songs") or []:
            if not (isinstance(s, dict) and _SLOT_RE.fullmatch(str(s.get("slot"))) and _HEX_RE.fullmatch(str(s.get("raw")))):
                continue
            songs.append({"slot": str(s["slot"]), "raw": str(s["raw"]), "name": str(s.get("name") or ""),
                          "note": str(s.get("note") or "")})
        out.append({"title": str(sl.get("title") or "Setlist"), "songs": songs})
    return out

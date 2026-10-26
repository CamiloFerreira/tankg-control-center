"""Starting points for new presets. Field keys as in model.FIELDS; three-zone knobs use the
middle of each third (zone 1 ≈ 21, zone 2 ≈ 63, zone 3 ≈ 106), which is an unverified guess."""
from __future__ import annotations

from .model import Preset

BASE = dict(amp_on=1, gate=10, amp_type=0, gain=20, treble=63, middle=63, bass=63, volume=90,
            mod_on=0, mod_fx=0, mod_speed=0, dly_on=0, dly_mix=0, dly_time=0,
            rvb_on=1, rvb_decay=20, rvb_mix=20, cab=1)

TEMPLATES: dict[str, tuple[dict, tuple[int, int, int]]] = {
    "Limpio": (dict(gain=15, treble=66), (255, 255, 255)),
    "Limpio con chorus": (dict(cab=5, mod_on=1, mod_fx=25, mod_speed=22, rvb_mix=25), (0, 200, 255)),
    "Crunch": (dict(amp_type=6, gain=45, treble=66, middle=68, cab=2, gate=15, rvb_mix=15), (255, 180, 0)),
    "Overdrive blues": (dict(amp_type=2, gain=45, middle=72, cab=4, gate=15, rvb_decay=63, rvb_mix=22),
                        (0, 120, 255)),
    "Distorsión": (dict(amp_type=7, gain=70, treble=64, middle=64, cab=2, gate=30, rvb_mix=12), (255, 60, 0)),
    "Alta ganancia": (dict(amp_type=5, gain=85, treble=66, middle=50, bass=70, cab=3, gate=45,
                           rvb_on=0, rvb_decay=0, rvb_mix=0), (255, 0, 0)),
    "Solo con delay": (dict(amp_type=7, gain=72, middle=72, volume=98, cab=8, gate=30,
                            dly_on=1, dly_mix=20, dly_time=60, rvb_mix=15), (255, 0, 120)),
    "Ambiental": (dict(amp_type=1, gain=25, cab=6, dly_on=1, dly_mix=105, dly_time=80,
                       rvb_decay=110, rvb_mix=40), (80, 0, 255)),
    "Acústica (piezo)": (dict(gain=15, treble=52, middle=56, bass=66, cab=6, gate=0,
                              rvb_mix=30), (255, 140, 0)),
    "Bajo": (dict(gain=10, treble=55, middle=66, bass=80, cab=6, gate=8,
                  rvb_on=0, rvb_decay=0, rvb_mix=0), (0, 80, 255)),
    "Vacío (todo apagado)": (dict(amp_on=0, gate=0, gain=0, volume=90, rvb_on=0, rvb_decay=0,
                                  rvb_mix=0, cab=0), (60, 60, 60)),
}


def build(name: str, like: Preset | None = None) -> Preset:
    """A preset from a template. Bytes the model does not map are taken from `like`
    (normally the preset being replaced) so unknown data keeps plausible values."""
    over, color = TEMPLATES[name]
    p = like.copy() if like is not None else Preset(bytearray(21))
    for key, value in {**BASE, **over}.items():
        p.set(key, value)
    p.color = color
    return p

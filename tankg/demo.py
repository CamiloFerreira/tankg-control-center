"""Demo mode, the same on the desktop (MainWindow.start_demo) and in the APK (startDemo in app.js):
a simulated pedal that holds nine banks of the band library, so the app can be tried without a
Tank-G. Its bank lives in memory only: nothing reaches a real pedal, the backups or the cloud, and
the names go to their own file (aliases.demo.json / "tankg.aliases.demo") so the real ones stay."""
from __future__ import annotations

from . import sysex
from .artists import BANKS
from .model import Bank, Preset

# Banks of artists.BANKS shown by the demo pedal, in order (exported to the APK by tools/export_ui.py).
DEMO_BANKS = ["Guitarra eléctrica", "Metallica", "Iron Maiden", "AC/DC", "Blind Guardian", "Korn",
              "Bajo limpio", "Guitarra clásica (nylon)", "Strato: limpios"]


def demo_bank() -> tuple[Bank, dict[int, str], dict[int, str]]:
    """(bank, {slot: preset name}, {bank: bank name}) of the demo pedal."""
    presets, preset_names, bank_names = [], {}, {}
    for b, name in enumerate(DEMO_BANKS):
        style = next((x for x in BANKS if x.name == name), BANKS[b])
        for i, p in enumerate(style.presets):
            preset_names[b * 4 + i] = p.name
            presets.append(p.build(Preset(bytearray(21))))
        bank_names[b] = style.name
    return Bank(presets), preset_names, bank_names


class SimulatedPedal:
    """Transport of the demo pedal: answers like the real one (bank reads, record writes with their
    ACK, commit) from an image in memory. Same behaviour as fakePedal() in protocol.js."""

    def __init__(self, image: bytes):
        self.mem = bytearray(image)
        self._out = bytearray()

    def write(self, data: bytes) -> None:
        if not data or data[0] != 0xF0:
            return   # Program Change: nothing to answer
        f = sysex.parse(data)
        if f.cls == sysex.CLS_READ:
            payload = bytes(self.mem[f.field:f.field + f.length])
            self._out += sysex.build(sysex.CLS_READ, sysex.CMD_READ + 8 * f.length, f.field, f.length, f.space, payload)
        elif f.cls == sysex.CLS_WRITE:
            if f.space == 0 and f.length:
                self.mem[f.field:f.field + f.length] = f.payload
            self._out += sysex.ACK

    def read(self, timeout: float) -> bytes:
        data, self._out = bytes(self._out), bytearray()
        return data

    def close(self) -> None:
        pass

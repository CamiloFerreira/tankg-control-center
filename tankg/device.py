"""Tank-G over ALSA rawmidi (/dev/snd/midiCxDy). No third-party dependencies.

Operations and their status (see research/FINDINGS.md):
  read bank      space 0, field 0, len 758                         verified
  write preset   CLS 09, CMD 0x41 + 8*21, space 0, field 2 + 21*slot  verified (ACK + read-back)
  commit         CLS 09, CMD 0x41, space F, len 0                   verified (ACK); survival
                                                                   across power cycle unverified
  select preset  MIDI Program Change 0..35 on channel 1             verified (pedal switched 1A->1B)
"""
from __future__ import annotations

import errno
import glob
import os
import re
import select
import time
from dataclasses import dataclass
from pathlib import Path

from . import sysex
from .model import BANK_LEN, Bank, Preset, REC_LEN, SLOTS

USB_ID = "4c4a:c755"   # generic Jieli id, shared by other M-VAVE pedals
SPACE_BANK = 0x0
SPACE_COMMIT = 0xF
COMMIT_FRAME = sysex.build(sysex.CLS_WRITE, sysex.CMD_READ, 0, 0, SPACE_COMMIT)


class DeviceError(Exception):
    """Error with a message meant for the user."""


@dataclass(frozen=True)
class DeviceInfo:
    card: int
    usb_id: str
    name: str
    rawmidi: str
    usb_path: str

    def describe(self) -> str:
        return f"{self.name} [{self.usb_id}] tarjeta ALSA {self.card}, {self.rawmidi}"


def find_devices() -> list[DeviceInfo]:
    found = []
    for card_dir in sorted(glob.glob("/proc/asound/card[0-9]*")):
        try:
            usb_id = Path(card_dir, "usbid").read_text().strip()
        except OSError:
            continue
        if usb_id != USB_ID:
            continue
        card = int(re.sub(r"\D", "", Path(card_dir).name))
        node = f"/dev/snd/midiC{card}D0"
        if not os.path.exists(node):
            continue
        try:
            name = Path(card_dir, "id").read_text().strip()
            usb_path = Path(card_dir, "usbbus").read_text().strip()
        except OSError:
            name, usb_path = "?", "?"
        found.append(DeviceInfo(card, usb_id, name, node, usb_path))
    return found


class RawMidi:
    """Minimal blocking-with-timeout rawmidi transport."""

    def __init__(self, path: str):
        self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as e:
            raise DeviceError(
                f"Sin permiso para abrir {path}. Añade tu usuario al grupo 'audio' "
                "(sudo usermod -aG audio $USER) y vuelve a iniciar sesión."
            ) from e
        except OSError as e:
            if e.errno == errno.EBUSY:
                raise DeviceError(f"{path} está en uso por otro programa (¿M-EFCS, amidi, un DAW?). Ciérralo.") from e
            raise DeviceError(f"No se pudo abrir {path}: {e.strerror}") from e
        self.drain()

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        deadline = time.monotonic() + 5
        while view:
            try:
                n = os.write(self.fd, view)
                view = view[n:]
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise DeviceError("Tiempo agotado escribiendo en la pedalera")
                select.select([], [self.fd], [], 0.1)
            except OSError as e:
                raise DeviceError(f"Error de escritura (¿desconectada?): {e.strerror}") from e

    def read(self, timeout: float) -> bytes:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return b""
        try:
            return os.read(self.fd, 4096)
        except BlockingIOError:
            return b""
        except OSError as e:
            raise DeviceError(f"Error de lectura (¿desconectada?): {e.strerror}") from e

    def drain(self) -> None:
        while self.read(0.05):
            pass


class TankG:
    def __init__(self, transport, info: DeviceInfo | None = None):
        self.t = transport
        self.info = info
        self._buf = bytearray()

    @classmethod
    def open(cls, info: DeviceInfo | None = None) -> "TankG":
        if info is None:
            devs = find_devices()
            if not devs:
                raise DeviceError("No se encontró la Tank-G (USB 4c4a:c755). ¿Está conectada y encendida?")
            info = devs[0]
        dev = cls(RawMidi(info.rawmidi), info)
        try:
            dev.read_bank()   # identifies the model: only a Tank-G returns an A5 5A 758-byte bank
        except DeviceError:
            dev.close()
            raise
        return dev

    def close(self) -> None:
        self.t.close()

    # transport helpers ----------------------------------------------------------

    def _next_frame(self, deadline: float) -> bytes | None:
        while True:
            start = self._buf.find(0xF0)
            if start >= 0:
                end = self._buf.find(0xF7, start)
                if end >= 0:
                    frame = bytes(self._buf[start:end + 1])
                    del self._buf[:end + 1]
                    return frame
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self._buf += self.t.read(min(left, 0.2))

    def _transact(self, frame: bytes, accept, timeout: float = 2.0):
        self._buf.clear()
        self.t.write(frame)
        deadline = time.monotonic() + timeout
        while (reply := self._next_frame(deadline)) is not None:
            result = accept(reply)
            if result is not None:
                return result
        return None

    # protocol -------------------------------------------------------------------

    def read_bank(self, retries: int = 3) -> Bank:
        frame = sysex.read(0, BANK_LEN, SPACE_BANK)

        def accept(reply: bytes):
            try:
                f = sysex.parse(reply)
            except ValueError:
                return None
            if f.cls == sysex.CLS_READ and f.length == BANK_LEN and len(f.payload) == BANK_LEN:
                return f.payload
            return None

        last = None
        for _ in range(retries):
            payload = self._transact(frame, accept)
            if payload is not None:
                try:
                    return Bank.from_bytes(payload)
                except ValueError as e:
                    raise DeviceError(f"El dispositivo respondió pero no parece una Tank-G: {e}") from e
            last = "sin respuesta"
            time.sleep(0.5)
        raise DeviceError(f"No se pudo leer el banco de presets ({last}).")

    def _expect_ack(self, frame: bytes, what: str) -> None:
        ok = self._transact(frame, lambda r: True if r == sysex.ACK else None, timeout=3.0)
        if not ok:
            raise DeviceError(f"La pedalera no confirmó: {what}")

    def write_preset(self, slot: int, preset: Preset) -> None:
        if not 0 <= slot < SLOTS:
            raise ValueError("slot out of range")
        data = preset.to_bytes()
        frame = sysex.build(sysex.CLS_WRITE, sysex.CMD_READ + 8 * REC_LEN,
                            Bank.record_offset(slot), REC_LEN, SPACE_BANK, data)
        self._expect_ack(frame, f"escritura del preset {slot}")
        self._expect_ack(COMMIT_FRAME, "commit")

    def select_preset(self, slot: int) -> None:
        if not 0 <= slot < SLOTS:
            raise ValueError("slot out of range")
        self.t.write(bytes([0xC0, slot]))

    def write_presets(self, target: Bank, slots: list[int], progress=None) -> Bank:
        """Write the given slots, then read back and verify. Returns the bank read back."""
        for n, slot in enumerate(slots):
            if progress:
                progress(n, len(slots), slot)
            self.write_preset(slot, target.presets[slot])
        time.sleep(0.5)
        after = self.read_bank()
        bad = [s for s in slots if after.presets[s] != target.presets[s]]
        if bad:
            raise DeviceError(f"Verificación fallida en slots {bad}: la pedalera no guardó lo enviado.")
        return after

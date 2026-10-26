"""Tank-G over MIDI: ALSA rawmidi on Linux (no dependencies), python-rtmidi elsewhere
(Windows WinMM, macOS CoreMIDI) or on Linux when rawmidi is unavailable.

Operations and their status (see research/FINDINGS.md):
  read bank      space 0, field 0, len 758                         verified
  write preset   CLS 09, CMD 0x41 + 8*21, space 0, field 2 + 21*slot  verified (ACK + read-back)
  commit         CLS 09, CMD 0x41, space F, len 0                   verified (ACK, survives
                                                                   a power cycle)
  select preset  MIDI Program Change 0..35 on channel 1             verified (pedal switched 1A->1B)
"""
from __future__ import annotations

import errno
import glob
import os
import queue
import re
import select
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import sysex
from .model import BANK_LEN, Bank, Preset, REC_LEN, SLOTS

USB_ID = "4c4a:c755"   # generic Jieli id, shared by other M-VAVE pedals
PORT_NAME = "USB Composite Device"   # MIDI port name of the Jieli chip on every OS
SPACE_BANK = 0x0
SPACE_COMMIT = 0xF
COMMIT_FRAME = sysex.build(sysex.CLS_WRITE, sysex.CMD_READ, 0, 0, SPACE_COMMIT)

try:
    import rtmidi
except ImportError:   # optional on Linux
    rtmidi = None


class DeviceError(Exception):
    """Error with a message meant for the user."""


@dataclass(frozen=True)
class DeviceInfo:
    backend: str          # "rawmidi" or "rtmidi"
    name: str
    address: str          # rawmidi node, or rtmidi port name
    out_port: int = -1    # rtmidi port indices
    in_port: int = -1

    def describe(self) -> str:
        return f"{self.name} [{self.backend}] {self.address}"


def _find_rawmidi() -> list[DeviceInfo]:
    found = []
    for card_dir in sorted(glob.glob("/proc/asound/card[0-9]*")):
        try:
            if Path(card_dir, "usbid").read_text().strip() != USB_ID:
                continue
        except OSError:
            continue
        card = int(re.sub(r"\D", "", Path(card_dir).name))
        node = f"/dev/snd/midiC{card}D0"
        if os.path.exists(node):
            found.append(DeviceInfo("rawmidi", f"{PORT_NAME} (tarjeta ALSA {card})", node))
    return found


def _port_key(name: str) -> str:
    """Port name without the per-OS decoration: Windows appends ' 0'/' 1', ALSA ' 28:0'."""
    return re.sub(r"\s+\d+(:\d+)?$", "", name).strip()


PORT_HINTS = ("usb composite device", "tank", "m-vave", "mvave", "jieli")


def list_midi_ports() -> tuple[list[str], list[str]]:
    """(input names, output names) seen by python-rtmidi. Raises DeviceError if unavailable."""
    if rtmidi is None:
        raise DeviceError("python-rtmidi no está disponible: no se pueden listar puertos MIDI.")
    try:
        midi_out, midi_in = rtmidi.MidiOut(), rtmidi.MidiIn()
        outs, ins = midi_out.get_ports(), midi_in.get_ports()
        midi_out.delete()
        midi_in.delete()
    except Exception as e:  # noqa: BLE001 - rtmidi raises its own error types
        raise DeviceError(f"No se pudo consultar el sistema MIDI: {e}") from e
    return ins, outs


def _looks_like_tankg(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in PORT_HINTS)


def _find_rtmidi() -> list[DeviceInfo]:
    try:
        ins, outs = list_midi_ports()
    except DeviceError:
        return []
    found = []
    used_in: set[int] = set()
    for oi, oname in enumerate(outs):
        if not _looks_like_tankg(oname):
            continue
        key = _port_key(oname)
        ii = next((i for i, n in enumerate(ins) if i not in used_in and _port_key(n) == key), None)
        if ii is None:
            ii = next((i for i, n in enumerate(ins) if i not in used_in and _looks_like_tankg(n)), None)
        if ii is not None:
            used_in.add(ii)
            found.append(DeviceInfo("rtmidi", PORT_NAME, oname, oi, ii))
    return found


def _find_selected(ports: tuple[str, str]) -> list[DeviceInfo]:
    """The ports the user picked in "Puerto MIDI…"; empty when they are not present."""
    try:
        ins, outs = list_midi_ports()
    except DeviceError:
        return []
    in_name, out_name = ports
    if in_name in ins and out_name in outs:
        return [DeviceInfo("rtmidi", "Puerto elegido", out_name, outs.index(out_name), ins.index(in_name))]
    return []


def find_devices(ports: tuple[str, str] | None = None) -> list[DeviceInfo]:
    """Manual selection (argument or saved setting) wins; otherwise automatic detection."""
    if ports is None:
        from .library import Settings
        ports = Settings().midi_ports
    if ports:
        return _find_selected(ports)
    if sys.platform.startswith("linux"):
        devs = _find_rawmidi()
        if devs:
            return devs
    return _find_rtmidi()


def open_transport(info: DeviceInfo):
    if info.backend == "rawmidi":
        return RawMidi(info.address)
    return RtMidi(info)


class RtMidi:
    """python-rtmidi transport: WinMM on Windows, CoreMIDI on macOS, ALSA seq on Linux."""

    def __init__(self, info: DeviceInfo):
        if rtmidi is None:
            raise DeviceError("Falta python-rtmidi: pip install python-rtmidi")
        self._q: queue.Queue[bytes] = queue.Queue()
        self.out = rtmidi.MidiOut()
        self.inp = rtmidi.MidiIn()
        try:
            self.out.open_port(info.out_port)
            self.inp.open_port(info.in_port)
        except Exception as e:  # noqa: BLE001 - rtmidi raises its own error types
            self.close()
            raise DeviceError(
                f"No se pudo abrir el puerto MIDI «{info.address}» ({e}). En Windows el puerto es "
                "exclusivo: cierra M-EFCS u otro programa que lo esté usando."
            ) from e
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        self.inp.set_callback(lambda event, _: self._q.put(bytes(event[0])))

    def close(self) -> None:
        for port in (getattr(self, "inp", None), getattr(self, "out", None)):
            if port is not None:
                try:
                    port.close_port()
                    port.delete()
                except Exception:  # noqa: BLE001 - closing must never raise
                    pass
        self.inp = self.out = None

    def write(self, data: bytes) -> None:
        try:
            self.out.send_message(list(data))
        except Exception as e:  # noqa: BLE001
            raise DeviceError(f"Error de escritura MIDI (¿desconectada?): {e}") from e

    def read(self, timeout: float) -> bytes:
        try:
            data = self._q.get(timeout=max(timeout, 0))
        except queue.Empty:
            return b""
        while True:   # drain whatever else already arrived
            try:
                data += self._q.get_nowait()
            except queue.Empty:
                return data


class RawMidi:
    """Minimal blocking-with-timeout ALSA rawmidi transport (Linux)."""

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
                raise DeviceError("No se encontró la Tank-G (puerto MIDI «USB Composite Device»). "
                                  "¿Está conectada por USB y encendida?")
            info = devs[0]
        dev = cls(open_transport(info), info)
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

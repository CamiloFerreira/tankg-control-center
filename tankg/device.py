"""Tank-G over MIDI: ALSA rawmidi on Linux (no dependencies), python-rtmidi elsewhere
(Windows WinMM, macOS CoreMIDI) or on Linux when rawmidi is unavailable.

Operations and their status (see research/FINDINGS.md):
  read bank      space 0, field 0, len 758                         verified
  write preset   CLS 09, CMD 0x41 + 8*21, space 0, field 2 + 21*slot  verified (ACK + read-back)
  commit         CLS 09, CMD 0x41, space F, len 0                   verified (ACK, survives
                                                                   a power cycle)
  select preset  MIDI Program Change 0..35 on channel 1             verified (pedal switched 1A->1B)

Bluetooth LE (Tank-G v2): same memory map with the framing of tankg/bleproto.py, over bleak
(TankGBle, verified on the pedal from Android 2026-10-27).
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

from . import bleproto, sysex
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
# Generic names Windows gives class-compliant devices without a product string (seen on a real
# Windows PC: "USB-Midi 0" in / "USB-Midi 1" out). Only accepted after the bank read identifies it.
WEAK_PORT_HINTS = ("usb-midi", "usb midi")


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


def _port_score(name: str) -> int:
    """2 = name points at the Tank-G, 1 = generic USB-MIDI name, 0 = unrelated. The pedal's BLE-MIDI
    port (BlueZ names it "TANK-Gv2_BLE Bluetooth") takes channel messages but ignores the editor
    SysEx: Bluetooth goes through TankGBle instead."""
    low = name.lower()
    if "bluetooth" in low or "_ble" in low:
        return 0
    if _looks_like_tankg(name):
        return 2
    low = name.lower()
    return 1 if any(h in low for h in WEAK_PORT_HINTS) else 0


def _find_rtmidi() -> list[DeviceInfo]:
    try:
        ins, outs = list_midi_ports()
    except DeviceError:
        return []
    found = []
    used_in: set[int] = set()
    for score in (2, 1):   # specific names first, generic USB-MIDI names last
        for oi, oname in enumerate(outs):
            if _port_score(oname) != score:
                continue
            key = _port_key(oname)
            ii = next((i for i, n in enumerate(ins) if i not in used_in and _port_key(n) == key), None)
            if ii is None:
                ii = next((i for i, n in enumerate(ins) if i not in used_in and _port_score(n) == score), None)
            if ii is not None:
                used_in.add(ii)
                found.append(DeviceInfo("rtmidi", PORT_NAME if score == 2 else "USB-MIDI genérico", oname, oi, ii))
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
    """Manual selection (argument or saved setting) wins; otherwise automatic detection: USB first,
    then the Bluetooth pedal saved in "Puerto MIDI…" (no radio scan here: it runs every 2 s)."""
    from .library import Settings
    settings = Settings()
    if ports is None:
        ports = settings.midi_ports
    if ports:
        return _find_selected(ports)
    devs = _find_rawmidi() if sys.platform.startswith("linux") else []
    devs = devs or _find_rtmidi()
    if not devs and settings.ble and ble_available():
        name, address = settings.ble
        devs = [DeviceInfo("ble", name, address)]
    return devs


def ble_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("bleak") is not None


def scan_bluetooth(timeout: float = 6.0) -> list[DeviceInfo]:
    """Nearby Tank-G pedals over Bluetooth LE (by name or by the editor service in the advert)."""
    if not ble_available():
        raise DeviceError("Falta la librería «bleak» para Bluetooth: pip install bleak")
    import asyncio

    from bleak import BleakScanner

    async def scan():
        return await BleakScanner.discover(timeout=timeout, return_adv=True)

    try:
        found = asyncio.run(scan())
    except Exception as e:  # noqa: BLE001 - bleak raises backend-specific errors
        raise DeviceError(f"No se pudo buscar por Bluetooth ({e}). ¿Está encendido el Bluetooth del PC?") from e
    out = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        if bleproto.SERVICE in [u.lower() for u in adv.service_uuids] or any(h in name.lower() for h in bleproto.NAME_HINTS):
            out.append(DeviceInfo("ble", f"{name or dev.address} (Bluetooth)", dev.address))
    return out


class BleLink:
    """bleak client on its own event-loop thread, with the same blocking read/write as the MIDI
    transports (read returns whatever notifications arrived)."""

    def __init__(self, address: str, timeout: float = 15.0):
        if not ble_available():
            raise DeviceError("Falta la librería «bleak» para Bluetooth: pip install bleak")
        import asyncio
        import threading

        self._q: queue.Queue[bytes] = queue.Queue()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = None
        try:
            self._call(self._connect(address, timeout), timeout + 5)
        except Exception as e:  # noqa: BLE001 - bleak raises backend-specific errors
            self.close()
            raise DeviceError(f"No se pudo conectar por Bluetooth con {address} ({e}). ¿Está encendida y libre "
                              "(sin la app del teléfono conectada)?") from e

    def _call(self, coro, timeout: float):
        import asyncio
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _connect(self, address: str, timeout: float) -> None:
        from bleak import BleakClient
        if sys.platform.startswith("linux"):
            # BlueZ: a pedal already known to the system is opened through its D-Bus object (fast, and
            # works while it is connected and therefore not advertising); bleak scans otherwise.
            from bleak.backends.device import BLEDevice
            path = f"/org/bluez/hci0/dev_{address.upper().replace(':', '_')}"
            try:
                self.client = BleakClient(BLEDevice(address, None, {"path": path, "props": {}}), timeout=timeout)
                await self.client.connect()
            except Exception:  # noqa: BLE001 - unknown to BlueZ yet: fall back to scanning
                self.client = None
        if self.client is None:
            self.client = BleakClient(address, timeout=timeout)
            await self.client.connect()
        acquire = getattr(getattr(self.client, "_backend", None), "_acquire_mtu", None)
        if acquire:   # BlueZ reports MTU 23 until asked; the pedal accepts 247 (bank reads 8x faster)
            try:
                await acquire()
            except Exception:  # noqa: BLE001 - keep the default MTU
                pass
        await self.client.start_notify(bleproto.RX, lambda _, data: self._q.put(bytes(data)))

    def write(self, data: bytes) -> None:
        size = max(20, (getattr(self.client, "mtu_size", 23) or 23) - 3)
        try:
            for i in range(0, len(data), size):
                self._call(self.client.write_gatt_char(bleproto.TX, data[i:i + size], response=False), 5)
        except Exception as e:  # noqa: BLE001
            raise DeviceError(f"Error de escritura Bluetooth (¿desconectada?): {e}") from e

    def read(self, timeout: float) -> bytes:
        try:
            data = self._q.get(timeout=max(timeout, 0))
        except queue.Empty:
            return b""
        while True:
            try:
                data += self._q.get_nowait()
            except queue.Empty:
                return data

    def close(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            try:
                self._call(client.disconnect(), 5)
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)


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
        self.bank: Bank | None = None   # bank read by open(); saves a second read in callers

    @classmethod
    def open(cls, info: DeviceInfo | None = None) -> "TankG":
        candidates = [info] if info is not None else find_devices()
        if not candidates:
            raise DeviceError("No se encontró la Tank-G. ¿Está conectada por USB y encendida? "
                              "Si lo está, elige el puerto en Pedalera → Puerto MIDI…")
        error: DeviceError | None = None
        for cand in candidates:
            try:
                dev = (TankGBle(BleLink(cand.address), cand) if cand.backend == "ble"
                       else cls(open_transport(cand), cand))
            except DeviceError as e:
                error = e
                continue
            try:
                dev.bank = dev.read_bank()   # identifies the model: only a Tank-G returns an A5 5A 758-byte bank
                return dev
            except DeviceError as e:
                dev.close()
                error = e
        raise error

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
        """Write the given slots, then read back and verify. Returns the bank read back.
        No pause before the read-back: the pedal already returns the new data after the ACK
        (research/FINDINGS.md, even before COMMIT)."""
        for n, slot in enumerate(slots):
            if progress:
                progress(n, len(slots), slot)
            self.write_preset(slot, target.presets[slot])
        if progress:
            progress(len(slots), len(slots), None)
        after = self.read_bank()
        bad = [s for s in slots if after.presets[s] != target.presets[s]]
        if bad:
            raise DeviceError(f"Verificación fallida en slots {bad}: la pedalera no guardó lo enviado.")
        return after


class TankGBle(TankG):
    """TankG over Bluetooth LE: same operations, bleproto framing (reads in blocks, ACKed writes)."""

    def __init__(self, transport, info: DeviceInfo | None = None):
        super().__init__(transport, info)
        self._deframer = bleproto.Deframer()
        self._pending: list[bleproto.Reply] = []

    def _next_reply(self, deadline: float):
        while True:
            if self._pending:
                return self._pending.pop(0)
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self._pending = self._deframer.push(self.t.read(min(left, 0.2)))

    def _ask(self, frame: bytes, accept, timeout: float = 1.5, retries: int = 3):
        for _ in range(retries):
            self._pending = []
            self.t.write(frame)
            deadline = time.monotonic() + timeout
            while (reply := self._next_reply(deadline)) is not None:
                result = accept(reply)
                if result is not None:
                    return result
        return None

    def read_mem(self, space: int, addr: int, length: int) -> bytes:
        frame = bleproto.frame(bleproto.READ, space, addr, length)
        data = self._ask(frame, lambda r: bleproto.read_reply_data(r, frame, length))
        if data is None:
            raise DeviceError("La pedalera no respondió por Bluetooth.")
        return data

    def write_mem(self, space: int, addr: int, data: bytes, what: str) -> None:
        frame = bleproto.frame(bleproto.WRITE, space, addr, len(data), data)
        ok = self._ask(frame, lambda r: True if r.cmd == bleproto.ACK_CMD and r.payload == b"\x00" else None,
                       timeout=3.0, retries=1)
        if not ok:
            raise DeviceError(f"La pedalera no confirmó: {what}")

    def read_bank(self, retries: int = 3) -> Bank:
        data = b"".join(self.read_mem(bleproto.SPACE_BANK, a, min(bleproto.CHUNK, BANK_LEN - a))
                        for a in range(0, BANK_LEN, bleproto.CHUNK))
        try:
            return Bank.from_bytes(data)
        except ValueError as e:
            raise DeviceError(f"El dispositivo respondió pero no parece una Tank-G: {e}") from e

    def write_preset(self, slot: int, preset: Preset) -> None:
        if not 0 <= slot < SLOTS:
            raise ValueError("slot out of range")
        self.write_mem(bleproto.SPACE_BANK, Bank.record_offset(slot), preset.to_bytes(), f"escritura del preset {slot}")
        self.write_mem(bleproto.SPACE_COMMIT, 0, b"", "commit")

    def select_preset(self, slot: int) -> None:
        if not 0 <= slot < SLOTS:
            raise ValueError("slot out of range")
        self.t.write(bleproto.frame(bleproto.WRITE, bleproto.SPACE_SELECT, slot, 1, b"\x01"))

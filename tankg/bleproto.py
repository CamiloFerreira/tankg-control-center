"""Framing of the editor protocol over Bluetooth LE (Tank-G v2), captured from the official app
(research/FINDINGS.md §5). Same memory map as USB; android/ui/js/protocol.js implements the same codec
and both are checked against the captured frames.

    00 59 | cmd | len u16 LE | 00 | f1 u32 LE | f2 u32 LE | data | ck     ck = 0xFF - sum(f1, f2, data)
    f1 = addr << 8 | mem      f2 = len << 8 | space << 4

mem 4 = presets (bank, preset in edition, status), mem 5 = AMP/CAB models (§9 of FINDINGS):
space 0 staging buffer of an AMP upload (blocks of 1015 bytes), A = audition it (data 01),
F = save it into the AMP slot `addr` (data 00); space 7 = raw flash of the 212992-byte AMP/CAB image
(9 AMP x 16 KB, then 8 CAB x 8 KB), written after erasing it with cmd 21 in 4 KB sectors:
    00 59 21 05 00 00 | f1 u32 LE | 70 | ck      (factory restore of M-EFCS, captured 2026-10-28)
"""
from __future__ import annotations

from dataclasses import dataclass

SERVICE = "0000ae40-0000-1000-8000-00805f9b34fb"
TX = "0000ae41-0000-1000-8000-00805f9b34fb"   # write without response
RX = "0000ae42-0000-1000-8000-00805f9b34fb"   # notify
READ, WRITE, ERASE, ACK_CMD = 0x23, 0x22, 0x21, 0x00
ACK = bytes.fromhex("00 59 00 01 00 00 00 ff")
CHUNK = 200          # bank read block (fits one notification with MTU 247)
SPACE_BANK, SPACE_SELECT, SPACE_COMMIT = 0x0, 0xE, 0xF
MEM_PRESETS, MEM_AMPCAB = 4, 5
SPACE_AMP_STAGE, SPACE_AMP_AUDITION, SPACE_AMP_SAVE = 0x0, 0xA, 0xF
AMP_CHUNK = 1015     # block size of M-EFCS for model uploads and flash writes
SPACE_FLASH, SECTOR, ERASE_OP = 0x7, 0x1000, 0x70
AMPCAB_LEN = 0x34000
NAME_HINTS = ("tank", "m-vave", "mvave", "jieli")


def frame(cmd: int, space: int, addr: int, length: int, data: bytes = b"", mem: int = MEM_PRESETS) -> bytes:
    payload = ((addr << 8) | mem).to_bytes(4, "little") + ((length << 8) | (space << 4)).to_bytes(4, "little") + bytes(data)
    ck = (0xFF - sum(payload)) & 0xFF
    return bytes([0x00, 0x59, cmd]) + len(payload).to_bytes(2, "little") + b"\x00" + payload + bytes([ck])


def erase_frame(addr: int, mem: int = MEM_AMPCAB) -> bytes:
    """Erase the 4 KB flash sector at `addr` of memory `mem` (0x70: constant sent by M-EFCS)."""
    payload = ((addr << 8) | mem).to_bytes(4, "little") + bytes([ERASE_OP])
    return bytes([0x00, 0x59, ERASE]) + len(payload).to_bytes(2, "little") + b"\x00" + payload + bytes([(0xFF - sum(payload)) & 0xFF])


@dataclass(frozen=True)
class Reply:
    cmd: int
    payload: bytes


class Deframer:
    """Splits the notification stream into frames (a reply can span several notifications)."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def push(self, data: bytes) -> list[Reply]:
        self.buf += data
        out = []
        while True:
            start = self.buf.find(b"\x00\x59")
            if start < 0:
                del self.buf[:-1]
                return out
            del self.buf[:start]
            if len(self.buf) < 6:
                return out
            total = 6 + int.from_bytes(self.buf[3:5], "little") + 1
            if len(self.buf) < total:
                return out
            f = bytes(self.buf[:total])
            del self.buf[:total]
            payload = f[6:-1]
            if (0xFF - sum(payload)) & 0xFF == f[-1]:
                out.append(Reply(f[2], payload))


def read_reply_data(reply: Reply, request: bytes, length: int) -> bytes | None:
    """Data of a read reply when it answers `request` (same f1/f2 echoed), else None."""
    if reply.cmd == READ and len(reply.payload) == 8 + length and reply.payload[:8] == request[6:14]:
        return reply.payload[8:]
    return None

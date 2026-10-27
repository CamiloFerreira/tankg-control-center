"""Framing of the editor protocol over Bluetooth LE (Tank-G v2), captured from the official app
(research/FINDINGS.md §5). Same memory map as USB; android/ui/js/protocol.js implements the same codec
and both are checked against the captured frames.

    00 59 | cmd | len u16 LE | 00 | f1 u32 LE | f2 u32 LE | data | ck     ck = 0xFF - sum(f1, f2, data)
    f1 = addr << 8 | 4        f2 = len << 8 | space << 4
"""
from __future__ import annotations

from dataclasses import dataclass

SERVICE = "0000ae40-0000-1000-8000-00805f9b34fb"
TX = "0000ae41-0000-1000-8000-00805f9b34fb"   # write without response
RX = "0000ae42-0000-1000-8000-00805f9b34fb"   # notify
READ, WRITE, ACK_CMD = 0x23, 0x22, 0x00
ACK = bytes.fromhex("00 59 00 01 00 00 00 ff")
CHUNK = 200          # bank read block (fits one notification with MTU 247)
SPACE_BANK, SPACE_SELECT, SPACE_COMMIT = 0x0, 0xE, 0xF
NAME_HINTS = ("tank", "m-vave", "mvave", "jieli")


def frame(cmd: int, space: int, addr: int, length: int, data: bytes = b"") -> bytes:
    payload = ((addr << 8) | 4).to_bytes(4, "little") + ((length << 8) | (space << 4)).to_bytes(4, "little") + bytes(data)
    ck = (0xFF - sum(payload)) & 0xFF
    return bytes([0x00, 0x59, cmd]) + len(payload).to_bytes(2, "little") + b"\x00" + payload + bytes([ck])


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

"""M-EFCS SysEx framing used by M-VAVE pedals (Jieli USB composite device).

Frame layout (documented publicly for the MK-300 by github.com/jpfaria/mvave, MIT;
the Tank-G answers the same framing -- verified live 2026-10-26 with a status read):

    F0 00 32 | CLS | CMD(4) | 02 | FIELD(4) | SUB(4) | pack7(payload + ck8) | F7

CMD, FIELD and SUB are u32 written as four little-endian 7-bit digits.
SUB = (length << 4) | space.  ck8 = 0xFB - (sum(payload) + sum(LE bytes of FIELD)
+ sum(LE bytes of (length << 8 | space << 4))) mod 256.
"""
from __future__ import annotations

from dataclasses import dataclass

MANUFACTURER = b"\x00\x32"

CLS_ACK = 0x01
CLS_WRITE = 0x09
CLS_READ = 0x0D

CMD_READ = 0x41
CMD_WRITE_U8 = 0x49
CMD_WRITE_U16 = 0x51

HEADER_LEN = 14
ACK = bytes.fromhex("f0 00 32 01 08 00 00 00 00 7f 01 f7")


def pack7(data: bytes) -> bytes:
    """8-bit bytes -> 7-bit stream, LSB first."""
    acc = nbits = 0
    out = bytearray()
    for b in data:
        acc |= b << nbits
        nbits += 8
        while nbits >= 7:
            out.append(acc & 0x7F)
            acc >>= 7
            nbits -= 7
    if nbits:
        out.append(acc & 0x7F)
    return bytes(out)


def unpack7(data: bytes) -> bytes:
    acc = nbits = 0
    out = bytearray()
    for b in data:
        acc |= (b & 0x7F) << nbits
        nbits += 7
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    return bytes(out)


def u32_to_7bit(v: int) -> bytes:
    return bytes((v >> s) & 0x7F for s in (0, 7, 14, 21))


def u32_from_7bit(b: bytes) -> int:
    return b[0] | b[1] << 7 | b[2] << 14 | b[3] << 21


def checksum(field: int, length: int, space: int, payload: bytes) -> int:
    sub8 = (length << 8) | (space << 4)
    total = sum(payload) + sum(field.to_bytes(4, "little")) + sum(sub8.to_bytes(4, "little"))
    return (0xFB - total) & 0xFF


@dataclass(frozen=True)
class Frame:
    cls: int
    cmd: int
    field: int
    length: int
    space: int
    payload: bytes


def build(cls: int, cmd: int, field: int, length: int, space: int, payload: bytes = b"") -> bytes:
    ck = checksum(field, length, space, payload)
    hdr = bytes([cls]) + u32_to_7bit(cmd) + b"\x02" + u32_to_7bit(field) + u32_to_7bit((length << 4) | space)
    return b"\xf0" + MANUFACTURER + hdr + pack7(payload + bytes([ck])) + b"\xf7"


def parse(frame: bytes, verify: bool = True) -> Frame:
    if frame[:3] != b"\xf0" + MANUFACTURER or frame[-1:] != b"\xf7":
        raise ValueError("not an M-VAVE frame")
    body = frame[3:-1]
    if len(body) < HEADER_LEN:
        raise ValueError("short frame")
    hdr, tail = body[:HEADER_LEN], body[HEADER_LEN:]
    sub = u32_from_7bit(hdr[10:14])
    length, space = sub >> 4, sub & 0xF
    field = u32_from_7bit(hdr[6:10])
    dec = unpack7(tail)
    payload, ck = (dec[:-1], dec[-1]) if dec else (b"", None)
    if verify and ck is not None and ck != checksum(field, length, space, payload):
        raise ValueError(f"bad checksum {ck:02x}")
    return Frame(hdr[0], u32_from_7bit(hdr[1:5]), field, length, space, payload)


def read(field: int, length: int, space: int) -> bytes:
    return build(CLS_READ, CMD_READ, field, length, space)


def split_sysex(raw: bytes) -> list[bytes]:
    frames, cur = [], None
    for b in raw:
        if b == 0xF0:
            cur = bytearray([b])
        elif cur is not None:
            cur.append(b)
            if b == 0xF7:
                frames.append(bytes(cur))
                cur = None
    return frames

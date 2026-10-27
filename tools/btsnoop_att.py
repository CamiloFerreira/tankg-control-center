"""Read-only analysis of an Android Bluetooth HCI snoop log (btsnoop_hci.log): prints the ATT
writes and notifications exchanged with a BLE device, to learn how an app talks to the pedal.

    python3 tools/btsnoop_att.py btsnoop_hci.log [--handles] [--limit N]

Only parses the capture; it never talks to any device.
"""
from __future__ import annotations

import argparse
import struct
import sys
from datetime import datetime, timedelta

ATT_OPS = {0x12: "WRITE_REQ", 0x52: "WRITE_CMD", 0x1B: "NOTIFY", 0x1D: "INDICATE", 0x0A: "READ_REQ",
           0x0B: "READ_RSP", 0x13: "WRITE_RSP", 0x02: "MTU_REQ", 0x03: "MTU_RSP", 0x01: "ERROR"}
EPOCH = datetime(1, 1, 1) + timedelta(microseconds=0)


def records(data: bytes):
    if data[:8] != b"btsnoop\0":
        raise SystemExit("no es un archivo btsnoop")
    off = 16
    while off + 24 <= len(data):
        orig, incl, flags, drops, ts = struct.unpack(">IIIIq", data[off:off + 24])
        off += 24
        pkt = data[off:off + incl]
        off += incl
        yield flags, ts, pkt


def att_packets(data: bytes):
    """(time, direction, conn handle, ATT opcode, attribute handle, value) for ACL/L2CAP CID 4."""
    reasm: dict[int, bytearray] = {}
    for flags, ts, pkt in records(data):
        if not pkt or pkt[0] != 0x02 or len(pkt) < 5:   # HCI ACL data
            continue
        direction = "rx" if flags & 1 else "tx"          # tx = phone -> device
        handle_flags, length = struct.unpack("<HH", pkt[1:5])
        conn, pb = handle_flags & 0x0FFF, (handle_flags >> 12) & 0x3
        body = pkt[5:5 + length]
        if pb in (0x0, 0x2):                               # first fragment
            reasm[conn] = bytearray(body)
        else:
            reasm.setdefault(conn, bytearray()).extend(body)
        buf = reasm[conn]
        if len(buf) < 4:
            continue
        l2len, cid = struct.unpack("<HH", buf[:4])
        if len(buf) < 4 + l2len:
            continue
        payload = bytes(buf[4:4 + l2len])
        reasm.pop(conn, None)
        if cid != 0x0004 or not payload:
            continue
        op = payload[0]
        attr = struct.unpack("<H", payload[1:3])[0] if op in (0x12, 0x52, 0x1B, 0x1D, 0x0A) and len(payload) >= 3 else None
        value = payload[3:] if attr is not None else payload[1:]
        yield ts, direction, conn, op, attr, value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--handles", action="store_true", help="solo resumen por handle")
    ap.add_argument("--limit", type=int, default=400)
    a = ap.parse_args()
    data = open(a.log, "rb").read()
    summary: dict[tuple, int] = {}
    n = 0
    for ts, d, conn, op, attr, value in att_packets(data):
        key = (d, ATT_OPS.get(op, hex(op)), attr)
        summary[key] = summary.get(key, 0) + 1
        if a.handles or n >= a.limit:
            continue
        n += 1
        print(f"{d} {ATT_OPS.get(op, hex(op)):<9} h={attr if attr is not None else '-':<5} {value.hex(' ')}")
    print("\nresumen:", file=sys.stderr)
    for (d, op, attr), c in sorted(summary.items(), key=lambda x: -x[1]):
        print(f"  {d} {op:<9} handle {attr}: {c}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Read-only probe: send one SysEx read and hexdump the decoded reply.

usage: python3 tools/probe_read.py FIELD LENGTH SPACE [--port hw:3,0,0]
Only CLS_READ frames are sent; nothing is written to the pedal.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tankg import sysex  # noqa: E402


def amidi_xfer(port: str, frame: bytes, timeout: float = 2.0) -> list[bytes]:
    out = subprocess.run(
        ["amidi", "-p", port, "-S", frame.hex(" "), "-d", "-t", str(timeout)],
        capture_output=True, text=True, timeout=timeout + 5,
    ).stdout
    return sysex.split_sysex(bytes.fromhex(out.replace("\n", " ")))


def hexdump(data: bytes) -> None:
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
        print(f"  {i:04x}: {chunk.hex(' '):<47}  {txt}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("field", type=lambda s: int(s, 0))
    ap.add_argument("length", type=lambda s: int(s, 0))
    ap.add_argument("space", type=lambda s: int(s, 0))
    ap.add_argument("--port", default="hw:3,0,0")
    ap.add_argument("--save")
    a = ap.parse_args()
    frame = sysex.read(a.field, a.length, a.space)
    print("TX", frame.hex(" "))
    replies = amidi_xfer(a.port, frame)
    if not replies:
        print("no reply")
    for r in replies:
        try:
            f = sysex.parse(r)
        except ValueError as e:
            print("RX unparsed", len(r), e, r[:32].hex(" "))
            continue
        print(f"RX cls={f.cls:02x} cmd={f.cmd:x} field={f.field} len={f.length} space={f.space} payload={len(f.payload)}")
        hexdump(f.payload)
        if a.save:
            Path(a.save).write_bytes(f.payload)


if __name__ == "__main__":
    main()

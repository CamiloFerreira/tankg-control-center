"""Experimental bank write (option C). Writes one 21-byte record to space 0, then reads back.

usage:
  python3 tools/write_test.py backup OUT.bin
  python3 tools/write_test.py record SLOT HEX21 [--commit] [--port hw:3,0,0]
  python3 tools/write_test.py bank FILE.bin [--commit]
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tankg import sysex  # noqa: E402

BANK_LEN = 758
REC_LEN = 21
HDR_LEN = 2
COMMIT = sysex.build(sysex.CLS_WRITE, sysex.CMD_READ, 0, 0, 0xF)


def xfer(port: str, frame: bytes, timeout: float = 2.0) -> list[bytes]:
    out = subprocess.run(
        ["amidi", "-p", port, "-S", frame.hex(" "), "-d", "-t", str(timeout)],
        capture_output=True, text=True, timeout=timeout + 5,
    ).stdout
    return sysex.split_sysex(bytes.fromhex(out.replace("\n", " ")))


def read_bank(port: str) -> bytes:
    for r in xfer(port, sysex.read(0, BANK_LEN, 0)):
        f = sysex.parse(r)
        if f.length == BANK_LEN and len(f.payload) == BANK_LEN:
            return f.payload
    raise RuntimeError("bank read failed")


def write_frame(field: int, data: bytes) -> bytes:
    return sysex.build(sysex.CLS_WRITE, sysex.CMD_READ + 8 * len(data), field, len(data), 0, data)


def send(port: str, label: str, frame: bytes) -> None:
    print(f"TX {label}: {frame.hex(' ')}")
    replies = xfer(port, frame, 3.0)
    for r in replies:
        print(f"RX {'ACK' if r == sysex.ACK else ''} {r.hex(' ')}")
    if not replies:
        print("RX none")


def diff(a: bytes, b: bytes) -> None:
    d = [(i, a[i], b[i]) for i in range(len(a)) if a[i] != b[i]]
    print(f"{len(d)} byte(s) differ")
    for i, x, y in d[:40]:
        slot = (i - HDR_LEN) // REC_LEN if i >= HDR_LEN else None
        print(f"  @{i} slot={slot} byte={(i - HDR_LEN) % REC_LEN if slot is not None else '-'}: {x:02x} -> {y:02x}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backup", "record", "bank"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--port", default="hw:3,0,0")
    a = ap.parse_args()

    before = read_bank(a.port)
    if a.mode == "backup":
        Path(a.args[0]).write_bytes(before)
        print("saved", a.args[0])
        return
    if a.mode == "record":
        slot, data = int(a.args[0]), bytes.fromhex(a.args[1])
        assert 0 <= slot < 36 and len(data) == REC_LEN
        send(a.port, "record", write_frame(HDR_LEN + REC_LEN * slot, data))
    else:
        data = Path(a.args[0]).read_bytes()
        assert len(data) == BANK_LEN and data[:2] == b"\xa5\x5a"
        send(a.port, "bank", write_frame(0, data))
    if a.commit:
        send(a.port, "commit", COMMIT)
    time.sleep(2)
    after = read_bank(a.port)
    diff(before, after)


if __name__ == "__main__":
    main()

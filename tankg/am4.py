"""AMP models (.am4data, the neural amp files of M-EFCS) for the TANK-G v2 (research/FINDINGS.md §9).

A file is 7868 bytes: "AM4\\0", a name and the float32 weights of a 16-unit GRU (PyTorch layout:
weight_ih, weight_hh, bias_ih, bias_hh, then the output layer) at offset 0x83C. Before uploading,
M-EFCS appends an "LMT\\0" block of 16 float32: the GRU state after one second of a decaying input,
which the pedal uses as the warm-up state. `lmt()` reproduces that computation bit for bit (the
fixed-point Q21 arithmetic and the 512-entry sigmoid/tanh tables of the official app), checked against
the blocks M-EFCS sent and the factory models.
"""
from __future__ import annotations

import math
import re
import struct
from pathlib import Path

MAGIC = b"AM4\x00"
FILE_LEN = 7868
LMT_LEN = 68
UPLOAD_LEN = FILE_LEN + LMT_LEN   # 7936
EXTENSION = ".am4data"

_WEIGHTS = 0x83C                  # 928 float32: 48 ih + 768 hh + 48 + 48 biases + 16 output
_H = 16
_Q = 21
_QF = struct.unpack("<f", struct.pack("<I", 0x49FFFFF8))[0]        # 2097151.0 (float32)
_C1, _C2 = struct.unpack("<2f", struct.pack("<2I", 0xC0DD0C55, 0x383E37C6))   # ln(0.001), 1/22050
_STEPS = 44100


class Am4Error(ValueError):
    pass


def _f32(x: float) -> float:
    return struct.unpack("<f", struct.pack("<f", x))[0]


def _i32(x: int) -> int:
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x & 0x80000000 else x


def _table(f, clamp: int | None = None):
    q = [int(f(-16 + i / 16) * (1 << 23)) for i in range(513)]   # Q23, x in [-16, 16) by 1/16
    if clamp:
        q = [max(-clamp, min(clamp, v)) for v in q]
    return q[:512], [q[i + 1] - q[i] for i in range(512)]


_SIG = _table(lambda x: 1 / (1 + math.exp(-x)))
_TANH = _table(math.tanh, (1 << 23) - 1)


def _act(v: int, table) -> int:
    tab, delta = table
    v = max(-0x2000000, min(0x1FFFFFF, v))
    i = (v + 0x2000000) >> 17
    return _i32((tab[i] + ((v & 0x1FFFF) * delta[i] >> 17)) >> 2)


def lmt(data: bytes) -> bytes:
    """The 68-byte LMT block M-EFCS appends to an AMP model before uploading it."""
    w = struct.unpack("<928f", data[_WEIGHTS:_WEIGHTS + 928 * 4])
    q = [int(_f32(v * _QF)) for v in w]
    rows = [[q[48 + 256 * g + 16 * j + k] for k in range(_H)] + [q[16 * g + j]] for g in range(3) for j in range(_H)]
    wr, wz, wn = rows[:_H], rows[_H:2 * _H], rows[2 * _H:]
    b_ih = [q[816 + 16 * g:816 + 16 * g + _H] for g in range(3)]
    b_hh = [q[864 + 16 * g:864 + 16 * g + _H] for g in range(3)]
    br = [_i32(a + b) for a, b in zip(b_ih[0], b_hh[0])]
    bz = [_i32(a + b) for a, b in zip(b_ih[1], b_hh[1])]
    h = [0] * _H
    for step in range(_STEPS):
        x = int(_f32(_f32(math.exp(_f32(_f32(step * _C1) * _C2))) * _QF))
        v = h + [x]
        r = [_act(_i32(_i32(sum(a * b for a, b in zip(wr[j], v)) >> _Q) + br[j]), _SIG) for j in range(_H)]
        z = [_act(_i32(_i32(sum(a * b for a, b in zip(wz[j], v)) >> _Q) + bz[j]), _SIG) for j in range(_H)]
        hn = [_i32(_i32(sum(a * b for a, b in zip(wn[j], h)) >> _Q) + b_hh[2][j]) for j in range(_H)]
        n = [_act(_i32(_i32((wn[j][_H] * x + r[j] * hn[j]) >> _Q) + b_ih[2][j]), _TANH) for j in range(_H)]
        h = [_i32(_i32((h[j] - n[j]) * z[j] >> _Q) + n[j]) for j in range(_H)]
    return b"LMT\x00" + struct.pack("<16f", *(_f32(v * 2.0 ** -_Q) for v in h))


def check(data: bytes) -> None:
    if data[:4] != MAGIC or len(data) not in (FILE_LEN, UPLOAD_LEN):
        raise Am4Error("No es un modelo de AMP para la Tank-G (archivo .am4data de M-EFCS).")
    if len(data) == UPLOAD_LEN and data[FILE_LEN:FILE_LEN + 4] != b"LMT\x00":
        raise Am4Error("Archivo .am4data dañado (bloque final desconocido).")


def upload_payload(data: bytes) -> bytes:
    """The 7936 bytes sent to the pedal: the model plus its LMT block (kept if already there)."""
    check(data)
    return bytes(data) if len(data) == UPLOAD_LEN else bytes(data) + lmt(data)


def name_from_path(path: str | Path) -> str:
    """Readable name from the file name (M-EFCS downloads are prefixed with a UUID)."""
    stem = Path(path).name
    stem = stem[:-len(EXTENSION)] if stem.lower().endswith(EXTENSION) else Path(stem).stem
    stem = re.sub(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_", "", stem, flags=re.I)
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip()[:40]

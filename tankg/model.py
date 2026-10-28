"""Tank-G preset bank: 2-byte magic + 36 records of 21 bytes (see research/FINDINGS.md).

Only the fields marked verified were checked against the official preset list and the
real pedal; everything else is kept as raw bytes and round-trips untouched.
"""
from __future__ import annotations

from dataclasses import dataclass

MAGIC = b"\xa5\x5a"
SLOTS = 36
REC_LEN = 21
BANK_LEN = len(MAGIC) + SLOTS * REC_LEN  # 758

# Verified: byte 5 against TANK-G_en.pdf, 36/36 factory presets.
AMP_MODELS = [
    "J120_CL", "J900_CL", "VAVE_TS", "RAT_OD", "VAVE_HTS",
    "VAVE_DS", "MS_GV2", "J900_HV", "MS_HIGAIN",
]
# Verified: byte 17 against TANK-G_en.pdf; 0 = no cabinet.
CAB_MODELS = [
    "(sin CAB)", "AC-SeVin", "JVM_1960_57", "MESA_412", "WANGS112",
    "VOX_AC30", "HIFI_YAMAHA", "EGNL_412", "V30_MD421",
]

OFF_AMP = 5
OFF_CAB = 17
OFF_KNOBS = 6          # inferred: 5 values 0-127 at bytes 6..10
KNOB_COUNT = 5
OFF_GATE = 4           # inferred: 0 on clean presets, 0x1B-0x2E on high-gain ones
OFF_COLOR = 18         # inferred: footswitch LED colour R, G, B (factory ff 00 00 = red)


@dataclass(frozen=True)
class Field:
    key: str
    offset: int
    label: str
    maximum: int
    verified: bool
    zones: tuple[str, ...] = ()   # knobs whose travel selects one of three types (manual)


# Layout inferred from the manual's front panel (21 bytes = 4 switches + gate + type + 5 EQ
# + 3x2 FX + cab + RGB) and from live/factory data; only TYPE and IR CAB are verified.
FIELDS = [
    Field("amp_on", 0, "AMP", 1, False),
    Field("mod_on", 1, "MOD", 1, False),
    Field("dly_on", 2, "DELAY", 1, False),
    Field("rvb_on", 3, "REVERB", 1, False),
    Field("gate", 4, "NOISE GATE", 127, False),
    Field("amp_type", 5, "TYPE", len(AMP_MODELS) - 1, True),
    Field("gain", 6, "GAIN", 127, False),
    Field("treble", 7, "TREBLE", 127, False),
    Field("middle", 8, "MIDDLE", 127, False),
    Field("bass", 9, "BASS", 127, False),
    Field("volume", 10, "VOLUME", 127, False),
    Field("mod_fx", 11, "MOD FX", 127, False, ("CHORUS", "PHASER", "TREMOLO")),
    Field("mod_speed", 12, "MOD SPEED", 127, False),
    Field("dly_mix", 13, "DLY MIX", 127, False, ("ANALOG", "TAPE", "DUAL")),
    Field("dly_time", 14, "DLY TIME", 127, False),
    Field("rvb_decay", 15, "RVB DECAY", 127, False, ("ROOM", "SPRING", "CLOUD")),
    Field("rvb_mix", 16, "RVB MIX", 127, False),
    Field("cab", 17, "IR CAB", len(CAB_MODELS) - 1, True),
]
FIELD_BY_KEY = {f.key: f for f in FIELDS}


def zone_of(field: Field, value: int) -> str:
    """Approximate type for a three-zone knob, assuming equal thirds (unverified)."""
    if not field.zones:
        return ""
    return field.zones[min(2, value * 3 // (field.maximum + 1))]


def zone_span(zone: int) -> tuple[int, int]:
    """Knob range that clearly selects zone 0-2, leaving out the dead spots around the limits
    (equal thirds and the dead-spot width are assumptions, unverified)."""
    return zone * 128 // 3 + 4, (zone + 1) * 128 // 3 - 5


def zone_gap(field: Field, value: int) -> bool:
    """True between two zones of a three-zone knob, where the manual says the module is off
    (values 38-45 and 81-88 with the assumed limits)."""
    return bool(field.zones) and any(zone_span(z)[1] < value < zone_span(z + 1)[0] for z in (0, 1))


def slot_name(slot: int) -> str:
    """0 -> '1A', 35 -> '9D' (bank = slot // 4 + 1, letter = ABCD[slot % 4])."""
    if not 0 <= slot < SLOTS:
        raise ValueError(f"slot out of range: {slot}")
    return f"{slot // 4 + 1}{'ABCD'[slot % 4]}"


def parse_slot(text: str) -> int:
    """Accepts '1B', '1b' or a 0-based index '1'."""
    t = text.strip().upper()
    if len(t) == 2 and t[0] in "123456789" and t[1] in "ABCD":
        return (int(t[0]) - 1) * 4 + "ABCD".index(t[1])
    n = int(t)
    if not 0 <= n < SLOTS:
        raise ValueError(f"slot out of range: {text}")
    return n


@dataclass
class Preset:
    raw: bytearray

    def __post_init__(self) -> None:
        if len(self.raw) != REC_LEN:
            raise ValueError(f"preset must be {REC_LEN} bytes, got {len(self.raw)}")
        self.raw = bytearray(self.raw)

    @classmethod
    def from_hex(cls, text: str) -> "Preset":
        return cls(bytearray.fromhex(text))

    def copy(self) -> "Preset":
        return Preset(bytearray(self.raw))

    def to_bytes(self) -> bytes:
        return bytes(self.raw)

    @property
    def amp(self) -> int:
        return self.raw[OFF_AMP]

    @amp.setter
    def amp(self, v: int) -> None:
        if not 0 <= v < len(AMP_MODELS):
            raise ValueError(f"AMP model out of range: {v}")
        self.raw[OFF_AMP] = v

    @property
    def cab(self) -> int:
        return self.raw[OFF_CAB]

    @cab.setter
    def cab(self, v: int) -> None:
        if not 0 <= v < len(CAB_MODELS):
            raise ValueError(f"CAB model out of range: {v}")
        self.raw[OFF_CAB] = v

    @property
    def knobs(self) -> list[int]:
        return list(self.raw[OFF_KNOBS:OFF_KNOBS + KNOB_COUNT])

    def set_knob(self, i: int, v: int) -> None:
        if not 0 <= i < KNOB_COUNT or not 0 <= v <= 0x7F:
            raise ValueError("knob index or value out of range")
        self.raw[OFF_KNOBS + i] = v

    def get(self, key: str) -> int:
        return self.raw[FIELD_BY_KEY[key].offset]

    def set(self, key: str, value: int) -> None:
        f = FIELD_BY_KEY[key]
        if not 0 <= value <= f.maximum:
            raise ValueError(f"{f.label}: valor fuera de rango 0..{f.maximum}: {value}")
        self.raw[f.offset] = value

    @property
    def color(self) -> tuple[int, int, int]:
        r, g, b = self.raw[OFF_COLOR:OFF_COLOR + 3]
        return r, g, b

    @color.setter
    def color(self, rgb: tuple[int, int, int]) -> None:
        self.raw[OFF_COLOR:OFF_COLOR + 3] = bytes(rgb)

    @property
    def amp_name(self) -> str:
        return AMP_MODELS[self.amp] if self.amp < len(AMP_MODELS) else f"? ({self.amp})"

    @property
    def cab_name(self) -> str:
        return CAB_MODELS[self.cab] if self.cab < len(CAB_MODELS) else f"? ({self.cab})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Preset) and self.raw == other.raw


class Bank:
    def __init__(self, presets: list[Preset]):
        if len(presets) != SLOTS:
            raise ValueError(f"bank must have {SLOTS} presets")
        self.presets = presets

    @classmethod
    def from_bytes(cls, data: bytes) -> "Bank":
        if len(data) != BANK_LEN:
            raise ValueError(f"bank image must be {BANK_LEN} bytes, got {len(data)}")
        if data[:2] != MAGIC:
            raise ValueError(f"bad bank magic {data[:2].hex()} (expected a55a)")
        return cls([Preset(bytearray(data[2 + REC_LEN * i:2 + REC_LEN * (i + 1)])) for i in range(SLOTS)])

    def to_bytes(self) -> bytes:
        return MAGIC + b"".join(p.to_bytes() for p in self.presets)

    def copy(self) -> "Bank":
        return Bank([p.copy() for p in self.presets])

    def diff_slots(self, other: "Bank") -> list[int]:
        return [i for i in range(SLOTS) if self.presets[i] != other.presets[i]]

    @staticmethod
    def record_offset(slot: int) -> int:
        return len(MAGIC) + REC_LEN * slot

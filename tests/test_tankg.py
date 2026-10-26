from pathlib import Path

import pytest

from tankg import library, sysex
from tankg.device import COMMIT_FRAME, DeviceError, TankG
from tankg.model import BANK_LEN, Bank, Preset, parse_slot, slot_name

HERE = Path(__file__).parent
ROOT = HERE.parent
LIVE = (HERE / "live_bank.bin").read_bytes()
FACTORY = ROOT / "research/factory/tankG_am4_preset.bin"

# Frames exchanged with the real pedal on 2026-10-26.
TX_READ_448_SPACE1 = "f0 00 32 0d 41 00 00 00 02 00 00 00 00 01 38 00 00 2a 00 f7"
TX_WRITE_9D = ("f0 00 32 09 69 01 00 00 02 61 05 00 00 50 02 00 00 01 00 00 08 30 04 02 22 2e 78 50 01 "
               "03 00 40 35 6b 12 14 38 50 0a 00 00 04 01 f7")
TX_COMMIT = "f0 00 32 09 41 00 00 00 02 00 00 00 00 0f 00 00 00 0b 00 f7"
TX_STATUS_POLL = "f0 00 32 0d 41 00 00 00 02 00 00 00 00 62 0a 00 00 05 01 f7"


def test_pack_roundtrip():
    data = bytes(range(256))
    assert sysex.unpack7(sysex.pack7(data))[:256] == data


def test_golden_frames():
    rec = bytes.fromhex("010000012308442e3c343000006b6b090507550000")
    frame = sysex.build(sysex.CLS_WRITE, sysex.CMD_READ + 8 * 21, 2 + 21 * 35, 21, 0, rec)
    assert frame.hex(" ") == TX_WRITE_9D
    assert COMMIT_FRAME.hex(" ") == TX_COMMIT
    assert sysex.read(0, 86, 2).hex(" ") == TX_STATUS_POLL
    assert sysex.read(0, 448, 1).hex(" ") == TX_READ_448_SPACE1


def test_parse_ack_and_reply():
    reply = sysex.build(sysex.CLS_READ, sysex.CMD_READ + 8 * 758, 0, 758, 0, LIVE)
    f = sysex.parse(reply)
    assert f.payload == LIVE and f.length == 758
    with pytest.raises(ValueError):
        sysex.parse(reply[:-3] + bytes([reply[-3] ^ 1]) + reply[-2:])


def test_slot_names():
    assert slot_name(0) == "1A" and slot_name(1) == "1B" and slot_name(35) == "9D"
    assert parse_slot("1b") == 1 and parse_slot("9D") == 35 and parse_slot("7") == 7
    with pytest.raises(ValueError):
        parse_slot("0A")


def test_bank_roundtrip_live():
    bank = Bank.from_bytes(LIVE)
    assert bank.to_bytes() == LIVE
    assert bank.presets[1].amp_name == "VAVE_HTS"
    assert bank.presets[35].cab_name == "V30_MD421"


@pytest.mark.skipif(not FACTORY.exists(), reason="factory bank not present")
def test_factory_matches_official_list():
    bank = library.load_bank(FACTORY)
    amps = [p.amp + 1 for p in bank.presets]
    cabs = [p.cab for p in bank.presets]
    # TANK-G_en.pdf, presets 1A..9D
    assert amps == [1, 3, 5, 7, 2, 4, 5, 8, 1, 4, 6, 9, 2, 4, 6, 9, 1, 3,
                    7, 8, 2, 4, 5, 9, 1, 4, 5, 8, 1, 3, 4, 8, 6, 7, 8, 9]
    assert cabs == [0, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5,
                    5, 5, 6, 6, 6, 6, 0, 7, 7, 7, 8, 8, 8, 8, 1, 3, 4, 6]


def test_bad_bank_rejected():
    with pytest.raises(ValueError):
        Bank.from_bytes(LIVE[:-1])
    with pytest.raises(ValueError):
        Bank.from_bytes(b"\x00\x00" + LIVE[2:])


def test_preset_fields():
    p = Bank.from_bytes(LIVE).presets[1].copy()
    p.amp = 0
    p.cab = 8
    p.set_knob(0, 127)
    assert p.raw[5] == 0 and p.raw[17] == 8 and p.raw[6] == 127
    with pytest.raises(ValueError):
        p.amp = 9


def test_preset_file_roundtrip(tmp_path):
    p = Bank.from_bytes(LIVE).presets[3]
    path = library.save_preset(p, tmp_path / "x.tgpreset", 3)
    assert library.load_preset(path) == p


class FakePedal:
    """Emulates the observed pedal behaviour: bank reads, record writes + ACK, commit ACK."""

    def __init__(self, image: bytes, drop_writes: bool = False):
        self.mem = bytearray(image)
        self.out = bytearray()
        self.drop_writes = drop_writes
        self.sent: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        if data[0] != 0xF0:
            return
        f = sysex.parse(data)
        if f.cls == sysex.CLS_READ:
            payload = bytes(self.mem[f.field:f.field + f.length])
            self.out += sysex.build(sysex.CLS_READ, sysex.CMD_READ + 8 * f.length, f.field, f.length, f.space, payload)
        elif f.cls == sysex.CLS_WRITE:
            if f.space == 0 and f.length and not self.drop_writes:
                self.mem[f.field:f.field + f.length] = f.payload
            self.out += sysex.ACK

    def read(self, timeout: float) -> bytes:
        data, self.out = bytes(self.out), bytearray()
        return data

    def close(self) -> None:
        pass


def test_device_write_verify_and_select():
    pedal = FakePedal(LIVE)
    dev = TankG(pedal)
    bank = dev.read_bank()
    target = bank.copy()
    target.presets[1].amp = 0
    after = dev.write_presets(target, [1])
    assert after.presets[1].amp == 0
    assert bytes(pedal.mem[:2]) == b"\xa5\x5a" and len(pedal.mem) == BANK_LEN
    assert sum(1 for s in pedal.sent if s == COMMIT_FRAME) == 1
    dev.select_preset(1)
    assert pedal.sent[-1] == b"\xc0\x01"


def test_device_detects_failed_write():
    dev = TankG(FakePedal(LIVE, drop_writes=True))
    target = dev.read_bank()
    target.presets[0].cab = 3
    with pytest.raises(DeviceError):
        dev.write_presets(target, [0])


def test_non_tankg_rejected():
    dev = TankG(FakePedal(b"\x00" * BANK_LEN))
    with pytest.raises(DeviceError):
        dev.read_bank()


def test_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "BACKUP_DIR", tmp_path)
    bank = Bank.from_bytes(LIVE)
    p1 = library.backup(bank)
    p2 = library.backup(bank)
    assert p1 != p2 and library.load_bank(p2).to_bytes() == LIVE


def test_aliases(tmp_path):
    path = tmp_path / "aliases.json"
    a = library.Aliases(path)
    a.set_preset(0, "Limpio")
    a.set_bank(5, "Nylon")
    a.swap(0, 3)
    b = library.Aliases(path)
    assert b.preset(0) == "" and b.preset(3) == "Limpio" and b.bank(5) == "Nylon"
    b.set_preset(3, "  ")
    assert library.Aliases(path).preset(3) == ""


def test_preset_file_keeps_name(tmp_path):
    p = Bank.from_bytes(LIVE).presets[0]
    path = library.save_preset(p, tmp_path / "x.tgpreset", 0, "Nylon natural")
    assert library.load_preset_file(path) == (p, "Nylon natural")

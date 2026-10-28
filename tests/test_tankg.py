import json
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
    steps = []
    after = dev.write_presets(target, [1], lambda n, total, s: steps.append((n, total, s)))
    assert steps == [(0, 1, 1), (1, 1, None)]   # last call = read-back verification
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


class _FakeRt:
    """Stands in for python-rtmidi with Windows-style port names."""
    outs = ["Microsoft GS Wavetable Synth 0", "USB Composite Device 1"]
    ins = ["USB Composite Device 0"]

    class MidiOut:
        def get_ports(self):
            return _FakeRt.outs

        def delete(self):
            pass

    class MidiIn:
        def get_ports(self):
            return _FakeRt.ins

        def delete(self):
            pass


def test_rtmidi_port_matching_windows_names(monkeypatch):
    from tankg import device
    monkeypatch.setattr(device, "rtmidi", _FakeRt)
    devs = device._find_rtmidi()
    assert len(devs) == 1 and devs[0].out_port == 1 and devs[0].in_port == 0


def test_rtmidi_port_matching_alsa_names(monkeypatch):
    from tankg import device
    monkeypatch.setattr(_FakeRt, "outs", ["Midi Through:Midi Through Port-0 14:0",
                                          "USB Composite Device:USB Composite Device MIDI 1 28:0"])
    monkeypatch.setattr(_FakeRt, "ins", list(_FakeRt.outs))
    monkeypatch.setattr(device, "rtmidi", _FakeRt)
    devs = device._find_rtmidi()
    assert [(d.out_port, d.in_port) for d in devs] == [(1, 1)]


def test_set_roundtrip(tmp_path):
    bank = Bank.from_bytes(LIVE)
    aliases = library.Aliases(tmp_path / "a.json")
    aliases.set_preset(4, "Uno")
    path = library.save_set(bank, [4, 5, 6, 7], tmp_path / "b.tgset", aliases, "Banco 2")
    title, items = library.load_set(path)
    assert title == "Banco 2" and [n for _, n in items] == ["Uno", None, None, None]
    assert [p for p, _ in items] == bank.presets[4:8]


def test_artist_banks_valid():
    from tankg import ai, artists
    from tankg.model import FIELD_BY_KEY, zone_of
    like = Bank.from_bytes(LIVE).presets[0]
    names = set()
    for bank in artists.BANKS:
        assert len(bank.presets) == 4 and bank.genre in artists.GENRES
        roles = [p.role for p in bank.presets]
        if roles[1] == "Rítmica":   # band banks: limpio/crunch, rítmica, variante, solo
            assert roles[0] in ("Limpio", "Crunch") and roles[2:] == ["Variante", "Solo"], bank.name
        for sp in bank.presets:
            assert len(sp.name) <= 20 and sp.name not in names, sp.name
            names.add(sp.name)
            p = sp.build(like)
            assert len(p.to_bytes()) == 21 and p.amp == sp.amp and p.cab == sp.cab
            assert 0 <= sp.gain <= 127 and 0 <= sp.gate <= 55 and all(0 <= v <= 127 for v in sp.eq)
            assert p.get("dly_on") == (sp.dly is not None)
            if sp.mod:
                assert zone_of(FIELD_BY_KEY["mod_fx"], p.get("mod_fx")).lower() == sp.mod[0]
            if sp.rvb:
                assert zone_of(FIELD_BY_KEY["rvb_decay"], p.get("rvb_decay")).lower() == sp.rvb[0]
    assert len(artists.BANKS) >= 100
    assert ai.system_prompt().count("\n- ") >= 10 and "Metallica Rítmica" in ai.system_prompt()


def test_manual_port_selection(monkeypatch, tmp_path):
    from tankg import device
    monkeypatch.setattr(_FakeRt, "outs", ["Microsoft GS Wavetable Synth 0", "Mi Pedal Raro 1"])
    monkeypatch.setattr(_FakeRt, "ins", ["Mi Pedal Raro 0"])
    monkeypatch.setattr(device, "rtmidi", _FakeRt)
    monkeypatch.setattr(device.sys, "platform", "win32")
    monkeypatch.setattr(library, "SETTINGS_FILE", tmp_path / "settings.json")
    assert device.find_devices() == []                       # unknown name: auto finds nothing
    library.Settings().set_midi_ports(("Mi Pedal Raro 0", "Mi Pedal Raro 1"))
    devs = device.find_devices()
    assert [(d.in_port, d.out_port) for d in devs] == [(0, 1)]
    library.Settings().set_midi_ports(None)
    assert device.find_devices() == []


def test_port_hints():
    from tankg import device
    assert device._looks_like_tankg("MIDIIN2 (TANK-G)")
    assert device._looks_like_tankg("M-VAVE MIDI 1")
    assert not device._looks_like_tankg("Microsoft GS Wavetable Synth")


def test_generic_windows_usb_midi_names(monkeypatch):
    from tankg import device
    monkeypatch.setattr(_FakeRt, "outs", ["Microsoft GS Wavetable Synth 0", "USB-Midi 1"])
    monkeypatch.setattr(_FakeRt, "ins", ["USB-Midi 0"])
    monkeypatch.setattr(device, "rtmidi", _FakeRt)
    devs = device._find_rtmidi()
    assert [(d.in_port, d.out_port) for d in devs] == [(0, 1)]


def test_specific_names_before_generic(monkeypatch):
    from tankg import device
    monkeypatch.setattr(_FakeRt, "outs", ["USB-Midi 0", "MIDIOUT2 (TANK-G) 1"])
    monkeypatch.setattr(_FakeRt, "ins", ["USB-Midi 0", "MIDIIN2 (TANK-G) 1"])
    monkeypatch.setattr(device, "rtmidi", _FakeRt)
    devs = device._find_rtmidi()
    assert devs[0].address == "MIDIOUT2 (TANK-G) 1" and devs[1].address == "USB-Midi 0"


def test_open_skips_candidates_that_are_not_a_tankg(monkeypatch):
    from tankg import device
    a = device.DeviceInfo("rtmidi", "x", "otro aparato")
    b = device.DeviceInfo("rtmidi", "x", "tank-g")
    monkeypatch.setattr(device, "find_devices", lambda: [a, b])
    monkeypatch.setattr(device, "open_transport",
                        lambda info: FakePedal(b"\x00" * BANK_LEN if info is a else LIVE))
    dev = TankG.open()
    assert dev.info is b


DESIGN = {"name": "Crunch AC/DC", "explanation": "x", "amp_on": True, "amp_type": 6, "gain": 50,
          "treble": 70, "middle": 68, "bass": 60, "volume": 95, "gate": 20, "cab": 2, "mod_on": False,
          "mod_type": "phaser", "mod_amount": 50, "mod_speed": 30, "dly_on": True, "dly_type": "tape",
          "dly_mix": 0, "dly_time": 40, "rvb_on": True, "rvb_type": "cloud", "rvb_decay": 100,
          "rvb_mix": 300, "led_color": [255, 128, 0]}


def test_ai_apply_design_zones_and_clamping():
    from tankg import ai
    from tankg.model import FIELD_BY_KEY, zone_of
    p = ai.apply_design(DESIGN, Bank.from_bytes(LIVE).presets[0])
    assert p.amp_name == "MS_GV2" and p.cab_name == "JVM_1960_57" and p.color == (255, 128, 0)
    assert zone_of(FIELD_BY_KEY["mod_fx"], p.get("mod_fx")) == "PHASER"
    assert zone_of(FIELD_BY_KEY["dly_mix"], p.get("dly_mix")) == "TAPE"
    assert zone_of(FIELD_BY_KEY["rvb_decay"], p.get("rvb_decay")) == "CLOUD"
    assert p.get("rvb_mix") == 127 and p.get("mod_on") == 0 and p.get("dly_on") == 1


def test_zone_gap_between_zones_only():
    from tankg import ai
    from tankg.model import FIELD_BY_KEY, zone_gap
    mod = FIELD_BY_KEY["mod_fx"]
    assert [v for v in range(128) if zone_gap(mod, v)] == [*range(38, 46), *range(81, 89)]
    assert not any(zone_gap(FIELD_BY_KEY["gain"], v) for v in range(128))
    # AI designs never land in a dead spot
    assert not any(zone_gap(mod, ai._zone_value(z, a)) for z in range(3) for a in range(101))


def test_ai_claude_request(monkeypatch):
    from tankg import ai
    seen = {}

    def fake_post(url, headers, body, timeout=120):
        seen.update(url=url, headers=headers, body=body)
        return {"content": [{"type": "tool_use", "name": "crear_preset", "input": DESIGN}]}
    monkeypatch.setattr(ai, "_post", fake_post)
    preset, name, _ = ai.generate(ai.AIConfig("claude", "sk-test"), "crunch", ai.INSTRUMENTS[0])
    assert name == "Crunch AC/DC" and preset.amp_name == "MS_GV2"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": "crear_preset"}


def test_ai_openai_request(monkeypatch):
    import json as _json
    from tankg import ai
    seen = {}

    def fake_post(url, headers, body, timeout=120):
        seen.update(url=url, headers=headers, body=body)
        return {"choices": [{"message": {"content": _json.dumps(DESIGN)}}]}
    monkeypatch.setattr(ai, "_post", fake_post)
    preset, _, _ = ai.generate(ai.AIConfig("openai", "sk-o"), "crunch", ai.INSTRUMENTS[1])
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer sk-o"
    assert "minimum" not in _json.dumps(seen["body"]["response_format"])
    assert preset.cab_name == "JVM_1960_57"


def test_ai_requires_key(monkeypatch):
    from tankg import ai
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ai.AIError):
        ai.generate(ai.AIConfig("claude", ""), "x", ai.INSTRUMENTS[0])


def test_ai_web_mode_parsing():
    import json as _json
    from tankg import ai
    prompt = ai.web_prompt("crunch", ai.INSTRUMENTS[0])
    assert "crunch" in prompt and '"rvb_type"' in prompt
    answer = "¡Claro! Aquí tienes:\n```json\n" + _json.dumps(DESIGN, ensure_ascii=False) + "\n```\nDisfrútalo."
    preset, name, _ = ai.from_text(answer)
    assert name == "Crunch AC/DC" and preset.amp_name == "MS_GV2"
    assert ai.parse_design_text("texto " + _json.dumps(DESIGN) + " más texto") is not None
    assert ai.parse_design_text("hola sin json") is None
    with pytest.raises(ai.AIError):
        ai.from_text('{"name": "incompleto"}')


def _bank_doc():
    designs = []
    for i, amp in enumerate([0, 6, 5, 7]):
        d = dict(DESIGN, name=f"P{i}", amp_type=amp)
        designs.append(d)
    return {"bank_name": "Rock", "presets": designs}


def test_ai_bank_claude(monkeypatch):
    from tankg import ai
    seen = {}

    def fake_post(url, headers, body, timeout=120):
        seen.update(body=body)
        return {"content": [{"type": "tool_use", "input": _bank_doc()}]}
    monkeypatch.setattr(ai, "_post", fake_post)
    likes = Bank.from_bytes(LIVE).presets[8:12]
    name, items = ai.generate_bank(ai.AIConfig("claude", "k"), "rock", ai.INSTRUMENTS[0], likes)
    assert name == "Rock" and [p.amp_name for p, _, _ in items] == ["J120_CL", "MS_GV2", "VAVE_DS", "J900_HV"]
    assert seen["body"]["tool_choice"]["name"] == "crear_banco"
    assert seen["body"]["tools"][0]["input_schema"]["properties"]["presets"]["minItems"] == 4


def test_ai_bank_web_text():
    import json as _json
    from tankg import ai
    prompt = ai.web_prompt("rock", ai.INSTRUMENTS[0], bank=True)
    assert "bank_name" in prompt and "EXACTAMENTE 4" in prompt
    text = "Aquí va:\n```json\n" + _json.dumps(_bank_doc()) + "\n```"
    assert ai.parse_bank_text(text) is not None and ai.parse_design_text(text) is None
    name, items = ai.bank_from_text(text, [None] * 4)
    assert name == "Rock" and len(items) == 4
    with pytest.raises(ai.AIError):
        ai.bank_from_text(_json.dumps({"bank_name": "x", "presets": [DESIGN]}), [None] * 4)


def test_updater_versions_and_checksums(monkeypatch):
    import json as _json
    from tankg import updater
    assert updater.newer("1.10.0", "1.9.9") and updater.newer("v2.0.0", "1.99.0")
    assert not updater.newer("1.5.0", "1.5.0") and not updater.newer("1.4.9", "1.5.0")
    sums = "abc123  TankG-linux-x86_64\nDEF456  TankG-windows-x64.exe\n"
    assert updater.expected_sha256(sums, "TankG-windows-x64.exe") == "def456"
    assert updater.expected_sha256(sums, "otro") is None
    doc = {"tag_name": "v9.9.9", "body": "Novedades\n## Verificar la descarga\nx",
           "assets": [{"name": updater.ASSET or "x", "browser_download_url": "https://e/bin"},
                      {"name": "SHA256SUMS", "browser_download_url": "https://e/sums"}]}
    payload = b"new binary"
    import hashlib
    files = {updater.API: _json.dumps(doc).encode(), "https://e/bin": payload,
             "https://e/sums": f"{hashlib.sha256(payload).hexdigest()}  {updater.ASSET}\n".encode()}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=30: files[url])
    rel = updater.latest()
    assert rel.version == "9.9.9" and rel.notes == "Novedades" and updater.newer(rel.version)
    if updater.ASSET:
        assert updater.download(rel) == payload
        files["https://e/bin"] = b"tampered"
        with pytest.raises(updater.UpdateError):
            updater.download(rel)


def test_version_matches_web_and_android():
    from tankg.version import __version__
    assert f'export const VERSION = "{__version__}"' in (ROOT / "android/ui/js/data.js").read_text(encoding="utf-8")
    assert "tankg/version.py" in (ROOT / "android/build.sh").read_text()


def test_json_files_are_utf8_and_read_old_ansi(tmp_path):
    bank = Bank.from_bytes(LIVE)
    path = tmp_path / "p.tgpreset"
    library.save_preset(bank.presets[0], path, 0, "Canción ñandú")
    assert library.load_preset_file(path)[1] == "Canción ñandú"
    aliases = library.Aliases(tmp_path / "a.json")
    aliases.set_preset(0, "Pingüino")
    library.save_set(bank, [0, 1], tmp_path / "s.tgset", aliases, "Año")
    assert (tmp_path / "s.tgset").read_bytes().decode("utf-8").count("Pingüino") == 1   # UTF-8 on every OS
    old = tmp_path / "old.tgset"   # written by a pre-1.5 Windows build (ANSI code page)
    old.write_bytes((tmp_path / "s.tgset").read_text(encoding="utf-8").encode("cp1252"))
    assert library.load_set(old)[0] == "Año"


def test_open_chat_prefers_registered_app(monkeypatch):
    from tankg import chatapps
    opened = []
    monkeypatch.setattr(chatapps, "scheme_handler", lambda scheme: scheme == "claude")
    monkeypatch.setattr(chatapps.sys, "platform", "linux")
    monkeypatch.setattr(chatapps.subprocess, "Popen", lambda args, **kw: opened.append(args))
    web = []
    assert chatapps.open_chat("Claude", web.append, "hola ñ") == "shared" and not web
    assert opened[-1][1] == "claude://claude.ai/new?q=hola%20%C3%B1"
    assert chatapps.open_chat("Claude", web.append, "x" * 20000) == "app" and opened[-1][1] == "claude://claude.ai/new"
    assert chatapps.open_chat("ChatGPT", web.append, "hola") == "web" and web == ["https://chatgpt.com/"]
    assert chatapps.open_chat("Gemini", web.append) == "web"


def test_prompts_fit_in_claude_desktop_prefill():
    """Claude Desktop cuts ?q= at 14336 characters: if the prompt grows past it, the user only gets the
    app opened (still works through the clipboard) — shorten the prompt or accept that."""
    from tankg import ai
    limit = ai.CHAT_APPS["Claude"]["limit"]
    for bank in (False, True):
        assert len(ai.web_prompt("x" * 120, ai.INSTRUMENTS[0], bank)) <= limit


# Bluetooth LE framing: frames captured from the official app on 2026-10-27 (same as tests/ui)
REC_9D = bytes.fromhex("010001011e07643e483c5f0000143c320f04ff0078")


def test_ble_golden_frames():
    from tankg import bleproto as b
    assert b.frame(b.READ, 2, 0, 4).hex(" ") == "00 59 23 08 00 00 04 00 00 00 20 04 00 00 d7"
    assert b.frame(b.WRITE, 0, 2 + 21 * 35, 21, REC_9D).hex(" ") == (
        "00 59 22 1d 00 00 04 e1 02 00 00 15 00 00 01 00 01 01 1e 07 64 3e 48 3c 5f 00 00 14 3c 32 0f 04 ff 00 78 4a")
    assert b.frame(b.WRITE, 0xF, 0, 0).hex(" ") == "00 59 22 08 00 00 04 00 00 00 f0 00 00 00 0b"
    assert b.frame(b.WRITE, 0xE, 35, 1, b"\x01").hex(" ") == "00 59 22 09 00 00 04 23 00 00 e0 01 00 00 01 f6"
    d = b.Deframer()
    reply = bytes.fromhex("0059231d000004e1020000150000010001011e07643e483c5f0000143c320f04ff00784a")
    assert d.push(b"\x7f" + reply[:10]) == []
    (r,) = d.push(reply[10:])
    assert r.cmd == 0x23 and r.payload[8:] == REC_9D


class FakeBlePedal:
    """Speaks the captured Bluetooth framing; replies arrive split like notifications."""

    def __init__(self, image: bytes):
        from tankg import bleproto
        self.mem = bytearray(image)
        self.out = bytearray()
        self.sent: list[bytes] = []
        self.deframer = bleproto.Deframer()
        self.amp_stage = bytearray(7936)
        self.amps: dict[int, bytes] = {}
        self.flash = bytearray(0x34000)
        self.erased = [False] * 52

    def write(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        for f in self.deframer.push(data):
            if f.cmd == 0x21:   # erase a 4 KB sector of the AMP/CAB flash
                self.erased[int.from_bytes(f.payload[0:4], "little") >> 20] = True
                self.out += bytes.fromhex("00 59 00 01 00 00 00 ff")
                continue
            f1, f2 = int.from_bytes(f.payload[0:4], "little"), int.from_bytes(f.payload[4:8], "little")
            addr, length, space = f1 >> 8, f2 >> 8, (f2 >> 4) & 0xF
            if f.cmd == 0x23:
                payload = f.payload[:8] + bytes(self.mem[addr:addr + length])
                self.out += b"\x00\x59\x23" + len(payload).to_bytes(2, "little") + b"\x00" + payload + bytes([(0xFF - sum(payload)) & 0xFF])
            else:
                if f1 & 0xFF == 5:   # AMP/CAB memory: staging buffer, audition, save into a slot
                    if space == 0:
                        self.amp_stage[addr:addr + length] = f.payload[8:]
                    elif space == 0xF:
                        self.amps[addr] = bytes(self.amp_stage)
                    elif space == 0x7:
                        assert all(self.erased[addr // 0x1000:(addr + length - 1) // 0x1000 + 1]), "write before erase"
                        self.flash[addr:addr + length] = f.payload[8:]
                elif space == 0 and length:
                    self.mem[addr:addr + length] = f.payload[8:]
                self.out += bytes.fromhex("00 59 00 01 00 00 00 ff")

    def read(self, timeout: float) -> bytes:
        data, self.out = bytes(self.out[:40]), self.out[40:]   # small chunks
        return data

    def close(self) -> None:
        pass


def test_tankg_ble_read_write_select():
    from tankg.device import TankGBle
    pedal = FakeBlePedal(LIVE)
    dev = TankGBle(pedal)
    bank = dev.read_bank()
    assert bank.to_bytes() == LIVE
    target = bank.copy()
    target.presets[35] = Preset(bytearray(REC_9D))
    after = dev.write_presets(target, [35])
    assert after.presets[35].to_bytes() == REC_9D
    assert any(s.hex(" ") == "00 59 22 08 00 00 04 00 00 00 f0 00 00 00 0b" for s in pedal.sent)
    dev.select_preset(35)
    assert pedal.sent[-1].hex(" ") == "00 59 22 09 00 00 04 23 00 00 e0 01 00 00 01 f6"


AM4_FIXTURE = (Path(__file__).parent / "am4_synthetic.am4data").read_bytes()


def test_am4_lmt_matches_native_and_capture_frames():
    """LMT of a synthetic model (random weights) as computed by the official native library."""
    from tankg import am4, bleproto as b
    model = AM4_FIXTURE[:am4.FILE_LEN]
    assert am4.lmt(model) == AM4_FIXTURE[am4.FILE_LEN:]
    assert am4.upload_payload(model) == AM4_FIXTURE == am4.upload_payload(AM4_FIXTURE)
    for bad in (b"XXXX" + model[4:], model[:-1], model + b"JUNK" * 17):
        with pytest.raises(am4.Am4Error):
            am4.check(bad)
    assert am4.name_from_path("/x/2d43beb2-89c9-497c-a474-f55b863bd259_RANDALL_RG100ES_100W__1987__CH_Clean.am4data") == \
        "RANDALL RG100ES 100W 1987 CH Clean"
    # frames captured from M-EFCS uploading a model to AMP 1 and AMP 3 (2026-10-28)
    stage = b.frame(b.WRITE, b.SPACE_AMP_STAGE, 0, b.AMP_CHUNK, model[:b.AMP_CHUNK], b.MEM_AMPCAB)
    assert stage[:14].hex(" ") == "00 59 22 ff 03 00 05 00 00 00 00 f7 03 00"
    assert b.frame(b.WRITE, 0xA, 0, 1, b"\x01", b.MEM_AMPCAB).hex(" ") == "00 59 22 09 00 00 05 00 00 00 a0 01 00 00 01 58"
    assert b.frame(b.WRITE, 0xF, 0, 1, b"\x00", b.MEM_AMPCAB).hex(" ") == "00 59 22 09 00 00 05 00 00 00 f0 01 00 00 00 09"
    assert b.frame(b.WRITE, 0xF, 2, 1, b"\x00", b.MEM_AMPCAB).hex(" ") == "00 59 22 09 00 00 05 02 00 00 f0 01 00 00 00 07"


def test_tankg_ble_upload_amp():
    from tankg import am4
    from tankg.device import DeviceError, TankG, TankGBle
    pedal = FakeBlePedal(LIVE)
    dev = TankGBle(pedal)
    steps = []
    dev.upload_amp(2, AM4_FIXTURE, lambda text, n, total: steps.append((n, total)))
    assert pedal.amps == {2: AM4_FIXTURE}
    assert pedal.mem == bytearray(LIVE)                       # the preset bank is untouched
    heads = [f[:7].hex(" ") + " " + f[10:12].hex(" ") for f in pedal.sent if f[:3] == b"\x00\x59\x22"]
    assert heads == ["00 59 22 ff 03 00 05 00 f7"] * 7 + ["00 59 22 47 03 00 05 00 3f"] + \
        ["00 59 22 09 00 00 05 a0 01"] + ["00 59 22 ff 03 00 05 00 f7"] * 7 + ["00 59 22 47 03 00 05 00 3f"] + \
        ["00 59 22 09 00 00 05 f0 01"]
    assert steps[-1] == (17, 17)
    with pytest.raises(DeviceError, match="Bluetooth"):
        TankG(FakePedal(LIVE)).upload_amp(0, AM4_FIXTURE)
    with pytest.raises(ValueError):
        dev.upload_amp(9, AM4_FIXTURE)
    with pytest.raises(ValueError):
        dev.upload_amp(0, AM4_FIXTURE[:am4.FILE_LEN])


@pytest.mark.skipif(not (ROOT / "research/factory/tankG_am3_ampCab.bin").exists(), reason="factory files not present")
def test_factory_ampcab_restore():
    from tankg import bleproto as b
    from tankg.device import DeviceError, TankG, TankGBle
    # erase frames captured from M-EFCS (first and last of the 52 sectors)
    assert b.erase_frame(0).hex(" ") == "00 59 21 05 00 00 05 00 00 00 70 8a"
    assert b.erase_frame(0x33000).hex(" ") == "00 59 21 05 00 00 05 00 30 03 70 57"
    for kind in library.FACTORY_SETS:
        image = library.factory_ampcab(kind)
        assert len(image) == 0x34000
        assert library.factory_bank(kind) is not None
        assert (ROOT / f"android/ui/factory/tankG_{library.FACTORY_AMPCAB[kind]}_ampCab.bin").read_bytes() == image   # same file in the APK
    image = library.factory_ampcab("am4")
    pedal = FakeBlePedal(LIVE)
    steps = []
    TankGBle(pedal).restore_ampcab(image, lambda text, n, total: steps.append(n))
    assert bytes(pedal.flash) == image and all(pedal.erased) and pedal.mem == bytearray(LIVE)
    flash_writes = [f for f in pedal.sent if f[:3] == b"\x00\x59\x22"]
    assert len(flash_writes) == 210 and flash_writes[0][6:14].hex(" ") == "05 00 00 00 70 f7 03 00"
    assert steps[-1] == 52 + 210
    with pytest.raises(DeviceError, match="Bluetooth"):
        TankG(FakePedal(LIVE)).restore_ampcab(image)


def test_factory_set_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "SETTINGS_FILE", tmp_path / "s.json")
    assert library.Settings().factory_set == "original"   # as it comes out of the box
    library.Settings().set_factory_set("am3")
    assert library.Settings().factory_set == "am3"
    if (ROOT / "research/factory/tankG_am3_preset.bin").exists():
        assert library.factory_bank().to_bytes() == library.factory_bank("am3").to_bytes() != library.factory_bank("am4").to_bytes()


def test_original_factory_set_and_names():
    original = (ROOT / "research/factory/tankG_original_preset.bin").read_bytes()
    assert library.factory_bank("original").to_bytes() == original
    assert original[:-2] == library.factory_bank("am3").to_bytes()[:-2]   # the AM3 presets, 9D's LED as the pedal keeps it
    names = library.factory_names("original")
    assert len(names["banks"]) == 9 and len(names["presets"]) == 36 and all(names["presets"].values())
    assert library.factory_names("am3") == names and library.factory_names("am4") == {"banks": {}, "presets": {}}


def test_aliases_keep_amp_names(tmp_path):
    a = library.Aliases(tmp_path / "a.json")
    a.set_preset(0, "Uno")
    a.set_amp(2, "RANDALL Clean")
    b = library.Aliases(tmp_path / "a.json")
    assert b.amp(2) == "RANDALL Clean" and b.amp(0) == "" and b.preset(0) == "Uno"
    b.set_amp(2, "")
    assert library.Aliases(tmp_path / "a.json").amps == {}


def test_bluetooth_midi_ports_are_not_used_for_sysex():
    from tankg import device
    assert device._port_score("TANK-Gv2_BLE:TANK-Gv2_BLE Bluetooth 128:0") == 0
    assert device._port_score("USB Composite Device 28:0") == 2


class FakeGoogle:
    """Google sign-in and a Drive with the app folder in memory (urllib calls of tankg.cloud)."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self.folders: dict[str, str] = {}
        self.polls = 0
        self.next_id = 1

    def __call__(self, method, url, data=None, headers=None, timeout=30):
        import json as _json
        import urllib.parse as up
        from tankg import cloud
        if url == cloud.DEVICE_URL:
            assert dict(up.parse_qsl(data.decode()))["scope"] == cloud.SCOPE
            return 200, b'{"device_code": "d", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device", "interval": 1, "expires_in": 60}'
        if url == cloud.TOKEN_URL:
            form = dict(up.parse_qsl(data.decode()))
            if form["grant_type"].endswith("device_code"):
                assert form["device_code"] == "d"
                self.polls += 1
                if self.polls == 2:   # Android cuts the network while the user is in the browser
                    raise cloud.NetworkError("Sin conexión con Google. ¿Hay internet?")
                if self.polls < 3:   # the user has not allowed it yet
                    return 428, b'{"error": "authorization_pending"}'
                return 200, b'{"access_token": "a", "refresh_token": "r", "expires_in": 3600}'
            return 200, b'{"access_token": "a2", "expires_in": 3600}'
        assert headers["Authorization"].startswith("Bearer ")
        if method == "GET" and url.startswith(cloud.FILES + "?"):
            q = dict(up.parse_qsl(up.urlparse(url).query))["q"]
            if cloud.FOLDER_MIME in q:
                found = [i for i, f in self.folders.items() if f"name = '{f}'" in q]
            else:
                found = [i for i, f in self.files.items() if f"'{f['parent']}' in parents" in q]
            names = {**self.folders, **{i: f["name"] for i, f in self.files.items()}}
            return 200, _json.dumps({"files": [{"id": i, "name": names[i], "modifiedTime": "t"} for i in found]}).encode()
        if method == "POST" and url.startswith(cloud.FILES + "?"):
            meta = _json.loads(data)
            assert meta["mimeType"] == cloud.FOLDER_MIME
            self.folders[f"d{len(self.folders) + 1}"] = meta["name"]
            return 200, _json.dumps({"id": f"d{len(self.folders)}"}).encode()
        if method == "GET" and url.endswith("?alt=media"):
            return 200, self.files[url.split("/")[-1].split("?")[0]]["body"]
        if method == "POST" and url.startswith(cloud.UPLOAD):
            parts = data.split(b"\r\n\r\n")
            meta = _json.loads(parts[1].split(b"\r\n--")[0])
            body = parts[2].rsplit(b"\r\n--", 1)[0]
            fid = f"f{self.next_id}"
            self.next_id += 1
            assert meta["parents"][0] in self.folders
            self.files[fid] = {"name": meta["name"], "body": body, "parent": meta["parents"][0]}
            return 200, _json.dumps({"id": fid}).encode()
        if method == "PATCH":
            self.files[url.split("/")[-1].split("?")[0]]["body"] = data
            return 200, b"{}"
        if method == "DELETE":
            del self.files[url.split("/")[-1]]
            return 204, b""
        raise AssertionError((method, url))


def test_cloud_sign_in_push_pull_history(monkeypatch):
    from tankg import cloud
    google = FakeGoogle()
    monkeypatch.setattr(cloud, "_request", google)
    monkeypatch.setattr(cloud, "CLIENT_ID", "id")
    monkeypatch.setattr(cloud, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(cloud.time, "sleep", lambda s: None)
    code = cloud.start_sign_in()
    assert code["user_code"] == "ABCD-EFGH" and code["url"] == "https://www.google.com/device"
    token = cloud.finish_sign_in(code)   # a network error while waiting does not end the sign-in
    assert google.polls == 3
    with pytest.raises(cloud.CloudError):
        cloud.finish_sign_in(code, should_stop=lambda: True)
    assert token == "r"
    drive = cloud.Drive(token)
    bank = Bank.from_bytes(LIVE)
    cloud.push(drive, cloud.make_doc(bank, {"1A": "Limpio ñ"}, {"1": "Rock"}, "Linux · pc"))
    doc = cloud.pull(drive)
    b2, presets, banks = cloud.parse_doc(doc)
    assert b2.to_bytes() == LIVE and presets == {"1A": "Limpio ñ"} and banks == {"1": "Rock"} and doc["device"] == "Linux · pc"
    cloud.push(drive, cloud.make_doc(bank, {"1A": "Limpio ñ"}, {"1": "Rock"}))   # identical: no new version
    assert len(google.files) == 1 and list(google.folders.values()) == [cloud.FOLDER]
    assert cloud.pull(cloud.Drive(token))["device"] == "Linux · pc"   # a new session finds the existing folder
    assert len(google.folders) == 1
    for i in range(cloud.HISTORY_KEEP + 3):   # every change keeps the previous one, pruned to HISTORY_KEEP
        changed = bank.copy()
        changed.presets[0] = Preset(bytearray([i % 2] * 21))
        doc = cloud.make_doc(changed, {"1A": f"v{i}"}, {})
        doc["updated"] = f"2026-10-27T10:{i:02d}:00+00:00"
        cloud.push(drive, doc)
    hist = cloud.history(drive)
    assert hist[0]["name"] == cloud.LATEST
    assert 1 <= len(hist) - 1 <= cloud.HISTORY_KEEP
    assert cloud.parse_doc(cloud.pull(drive))[1] == {"1A": f"v{cloud.HISTORY_KEEP + 2}"}


def test_pack_roundtrip_remap_and_missing_models(tmp_path):
    from tankg import pack
    bank = Bank.from_bytes(LIVE)
    for s in (4, 5):
        bank.presets[s].raw[5] = 2          # these two use AMP 3, replaced by an uploaded model
    model = AM4_FIXTURE[:7868]
    doc, missing = pack.make(bank, [4, 5, 6, 7], {4: "Uno", 6: "Tres"}, {"2": "Banco Dos"}, {"3": "Mi AMP"}, {2: model}, "Mi pack")
    assert missing == [] and [a["slot"] for a in doc["amps"]] == [3] and doc["banks"] == {"2": "Banco Dos"}
    path = pack.save(doc, tmp_path / "x.tgpack")
    p = pack.load(path)
    assert p.kind == "bank" and p.title == "Mi pack" and p.banks == {"2": "Banco Dos"}
    assert [(o, n) for o, _, n in p.presets] == [(4, "Uno"), (5, None), (6, "Tres"), (7, None)]
    assert len(p.amps) == 1 and p.amps[0].slot == 2 and p.amps[0].data == model and p.amps[0].name == "Mi AMP"
    moved = pack.remap([q for _, q, _ in p.presets], {2: 6})
    assert [q.amp for q in moved] == [6 if bank.presets[s].amp == 2 else bank.presets[s].amp for s in (4, 5, 6, 7)]
    assert [q.amp for q in moved[:2]] == [6, 6]
    _, missing = pack.make(bank, [4], {}, {}, {"3": "Mi AMP"}, {}, None)   # model not kept on this device
    assert missing == [2]
    with pytest.raises(ValueError):
        pack.parse({"format": "otro"})
    bad = dict(doc, amps=[{"slot": 3, "name": "x", "data": "QUJD"}])
    with pytest.raises(ValueError):
        pack.parse(bad)


def test_model_store(tmp_path):
    store = library.ModelStore(tmp_path / "amps")
    assert store.all() == {}
    store.put(4, b"AM4\x00x")
    assert store.get(4) == b"AM4\x00x" and list(store.all()) == [4]
    store.clear()
    assert store.all() == {}


def test_band_packs_are_references_with_credits(monkeypatch):
    """The packs shipped with the apps hold no third-party model: only a reference to its community
    publication and its author; the model is downloaded once and kept on the device."""
    from tankg import pack
    packs = pack.builtin()
    assert len(packs) >= 10
    for path, p in packs:
        assert p.kind == "bank" and p.amps, path.name
        for amp in p.amps:
            assert amp.data is None and amp.community["article"] > 0 and amp.credit["author"], path.name
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert all("data" not in a for a in raw["amps"])
    amp = packs[0][1].amps[0]
    assert pack.missing([packs[0][1]])[0] is amp and not pack.cached(amp)
    calls = []

    class Answer:
        def __init__(self, url):
            calls.append(url)

        def read(self):
            return AM4_FIXTURE[:7868]

    monkeypatch.setattr(pack.urllib.request, "urlopen", lambda req, timeout=0: Answer(req.full_url))
    assert pack.fetch(amp) == AM4_FIXTURE[:7868]
    assert "articleId=" in calls[0] and pack.cached(amp)
    assert pack.fetch(amp) == AM4_FIXTURE[:7868] and len(calls) == 1      # kept on the device: no second download
    monkeypatch.setattr(pack.urllib.request, "urlopen", lambda req, timeout=0: type("A", (), {"read": lambda self: b"junk"})())
    other = next(a for _, p in packs for a in p.amps if not pack.cached(a))
    with pytest.raises(ValueError):
        pack.fetch(other)                                                   # not an AM4 model: refused


def test_ai_knows_uploaded_amps():
    from tankg import ai
    plain = ai.web_prompt("rítmica de Pantera", ai.INSTRUMENTS[0])
    assert "AMP SUBIDOS" not in plain
    text = ai.web_prompt("rítmica de Pantera", ai.INSTRUMENTS[0], False, {"9": "Randall RG100ES '87", "8": "Walk"})
    assert "TYPE 8 (amp_type 7): «Walk»" in text and "TYPE 9 (amp_type 8): «Randall RG100ES '87»" in text
    assert text.index("TYPE 8") < text.index("TYPE 9")


def test_amp_sources_and_preset_needs(tmp_path):
    from tankg import cloud
    a = library.Aliases(tmp_path / "a.json")
    a.set_amp(8, "Randall", {"article": 7414, "file": "x.am4Data"})
    a.set_preset_amp(32, {"slot": 8, "name": "Randall", "source": {"article": 7414, "file": "x.am4Data"}})
    b = library.Aliases(tmp_path / "a.json")
    assert b.amp_sources == {"9": {"article": 7414, "file": "x.am4Data"}}
    p = Preset(bytearray(21))
    p.raw[5] = 8
    assert b.missing_amp(32, p) is None                       # TYPE 9 holds the model the preset needs
    b.set_amp(8, "Otro AMP")                                  # from a file: no source; the preset's model is gone
    assert b.amp_sources == {} and b.missing_amp(32, p)["name"] == "Randall"
    p.raw[5] = 2
    assert b.missing_amp(32, p) is None                       # the preset doesn't use that TYPE any more
    bank = Bank.from_bytes(LIVE)
    doc = cloud.make_doc(bank, {}, {}, amps={"9": "Randall"}, amp_sources=a.amp_sources, preset_amps=a.preset_amps)
    assert cloud.doc_amp_sources(doc) == a.amp_sources and cloud.doc_preset_amps(doc) == a.preset_amps
    assert "ampSources" not in cloud.make_doc(bank, {}, {})["aliases"]   # older documents keep their key

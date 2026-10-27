from pathlib import Path

import pytest

from tankg import library, sysex
from tankg.device import COMMIT_FRAME, DeviceError, TankG
from tankg.model import BANK_LEN, Bank, parse_slot, slot_name

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
    assert f'export const VERSION = "{__version__}"' in (ROOT / "web/js/data.js").read_text(encoding="utf-8")
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

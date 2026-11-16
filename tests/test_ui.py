"""Web/Android app: generated data must be current and the JS protocol must pass its tests
(same golden frames as the Python codec). Skipped when node is not installed."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_ui_data_is_current():
    import export_ui
    current = export_ui.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")   # Windows checkouts may use CRLF
    assert current == export_ui.render(), \
        "android/ui/js/data.js desactualizado: ejecuta tools/export_ui.py"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_ui_protocol():
    r = subprocess.run(["node", str(ROOT / "tests/ui/protocol.test.mjs")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_ui_ai_and_files_match_python(tmp_path):
    """Same apply_design, browser prompt and interchangeable .tgpreset/.tgset files in JS and Python."""
    import json
    import itertools
    from tankg import ai, am4, artists, cloud, library, pack, setlist
    from tankg.model import FIELDS, Bank, Preset, zone_gap
    live = (ROOT / "tests/live_bank.bin").read_bytes()
    bank = Bank.from_bytes(live)
    designs = []
    for i, b in enumerate(artists.BANKS[::7]):
        d = b.presets[i % 4].design()
        like = bank.presets[i]
        designs.append({"design": d, "like": like.to_bytes().hex(),
                        "expect": ai.apply_design(d, like).to_bytes().hex(),
                        "expectBlank": ai.apply_design(d, None).to_bytes().hex()})
    odd = dict(designs[0]["design"], gain=999, mod_type="nope", dly_mix=-5, led_color=[300, -1])
    designs.insert(0, {"design": odd, "like": None, "expect": ai.apply_design(odd).to_bytes().hex(),
                       "expectBlank": ai.apply_design(odd).to_bytes().hex()})
    prompts = [{"desc": d, "instrument": ins, "bank": bk, "expect": ai.web_prompt(d, ins, bk)}
               for d, ins, bk in [("crunch tipo AC/DC ", ai.INSTRUMENTS[0], False), ("banco de doom", ai.INSTRUMENTS[3], True)]]
    prompts.append({"desc": "Pantera", "instrument": ai.INSTRUMENTS[0], "bank": True, "amps": {"9": "Randall RG100ES", "8": "Walk"},
                    "expect": ai.web_prompt("Pantera", ai.INSTRUMENTS[0], True, {"9": "Randall RG100ES", "8": "Walk"})})
    preset_py = tmp_path / "p.tgpreset"
    library.save_preset(bank.presets[3], preset_py, 3, "Mi Preset ñ")
    aliases = library.Aliases(tmp_path / "a.json")
    aliases.set_preset(8, "Ocho")
    set_py = tmp_path / "s.tgset"
    library.save_set(bank, [8, 9, 10, 11], set_py, aliases, "Banco 3")
    names = {"1A": "Cierre ñ", "2A": "Intro"}
    songs = [setlist.song(bank, names, s, n) for s, n in ((4, "capo 2"), (20, ""), (0, "fade"))]
    songs.append(dict(setlist.song(bank, names, 9), raw="00" * 21))   # edited and unnamed: lost
    golden = {"designs": designs, "prompts": prompts, "presetPy": preset_py.read_text(), "presetRaw": bank.presets[3].to_bytes().hex(),
              "presetName": "Mi Preset ñ", "setPy": set_py.read_text(), "setTitle": "Banco 3",
              "setRaws": [bank.presets[s].to_bytes().hex() for s in range(8, 12)], "bank": live.hex(),
              "gaps": {f.key: [v for v in range(f.maximum + 1) if zone_gap(f, v)] for f in FIELDS},
              "am4Tables": {"sig": am4._SIG, "tanh": am4._TANH},
              "packPy": json.dumps(pack.make(bank, [4, 5, 6, 7], {4: "Uno ñ"}, {"2": "Banco"}, {str(bank.presets[4].amp + 1): "Mi AMP"},
                                             {bank.presets[4].amp: (ROOT / "tests/am4_synthetic.am4data").read_bytes()[:7868]}, "Pack")[0]),
              "packAmp": bank.presets[4].amp,
              "setlist": [{"order": o, "start": st, "source": setlist.layout(o, st),
                           "names": setlist.move_names({"6A": "Intro", "1B": "Cierre ñ"}, setlist.layout(o, st)),
                           "songs": setlist.refresh(songs, setlist.apply(bank, setlist.layout(o, st)),
                                                    setlist.move_names(names, setlist.layout(o, st))),
                           "slots": setlist.resolve(songs, setlist.apply(bank, setlist.layout(o, st)),
                                                    setlist.move_names(names, setlist.layout(o, st)))}
                          for o, st in [([20, 3, 0, 35, 5], 2), ([0, 1, 2], 0), ([35, 34, 33, 32], 30), (list(range(36))[::-1], 0)]],
              "setlistSongs": songs, "setlistNames": names,
              "setlistText": setlist.text("Show ", songs + [{"slot": "9D", "raw": "", "name": "", "note": ""}], [3, 7, 0, None, None]),
              "startup": [[list(k), cloud.startup_action(*k)] for k in itertools.product(["C", "S", None], ["C", "L", None],
                                                                                     ["S", None], ["P", None])],
              "setlistDirty": [{"title": "", "songs": [{"slot": "6A", "raw": "00ff", "name": 3}, {"slot": "77", "raw": "x"}, 5]}, 3],
              "setlistClean": setlist.clean([{"title": "", "songs": [{"slot": "6A", "raw": "00ff", "name": 3}, {"slot": "77", "raw": "x"}, 5]}, 3])}
    from tankg import updater
    from tankg.model import check_writable

    def _accepts(fn, *a):
        try:
            fn(*a)
            return True
        except (ValueError, ai.AIError):
            return False
    updates = []
    for body, latest, current in [("Notas\n<!-- tankg-min-version: 1.11.0 -->", "1.11.0", "1.10.2"),
                                  ("<!--tankg-min-version:v1.11-->", "1.12.0", "1.11.0"),
                                  ("<!-- tankg-min-version: 1.11.0 -->", "1.12.0", "1.10.9"),
                                  ("sin marca", "2.0.0", "1.0.0"), ("<!-- tankg-min-version: 3.0.0 -->", "1.0.0", "1.0.0")]:
        rel = updater.Release(latest, "", None, None, updater.min_version(body))
        updates.append({"body": body, "latest": latest, "current": current, "min": rel.min_version,
                        "required": updater.required(rel, current)})
    raws = [bank.presets[0].to_bytes().hex(), "00" * 5 + "09" + "00" * 15, "00" * 17 + "ff" + "000000", "00" * 20]
    golden["records"] = [{"raw": r, "ok": len(r) == 42 and _accepts(check_writable, Preset.from_hex(r))} for r in raws]
    golden["urls"] = [{"url": u, "ok": _accepts(ai.check_url, u)} for u in
                      ["https://api.anthropic.com", "http://localhost:11434/v1", "http://192.168.1.5:1234/v1", "http://mypc:8080",
                       "http://evil.com/v1", "file:///etc/passwd", "http://8.8.8.8", "http://10.0.0.2", "http://172.20.1.1",
                       "http://172.40.1.1", "ftp://x.com"]]
    golden["updates"] = updates
    assert [u["required"] for u in updates] == [True, False, True, False, False]
    golden_pack = json.loads(golden["packPy"])
    gfile = tmp_path / "golden.json"
    gfile.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "tests/ui/parity.test.mjs"), str(gfile)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout
    out = json.loads(r.stdout)
    (tmp_path / "js.tgpreset").write_text(out["preset"], encoding="utf-8")
    (tmp_path / "js.tgset").write_text(out["set"], encoding="utf-8")
    preset, name = library.load_preset_file(tmp_path / "js.tgpreset")
    assert preset == bank.presets[3] and name == "Mi Preset ñ"
    title, items = library.load_set(tmp_path / "js.tgset")
    assert title == "Mi banco" and [p for p, _ in items] == bank.presets[4:8] and items[1][1] is None
    assert isinstance(items[0][0], Preset)
    (tmp_path / "js.tgpack").write_text(out["pack"], encoding="utf-8")
    from_js = pack.load(tmp_path / "js.tgpack")
    assert json.loads(out["pack"])["presets"] == golden_pack["presets"] and from_js.banks == {"2": "Banco"}
    assert [(a.slot, a.name, a.data) for a in from_js.amps] == [(golden["packAmp"], "Mi AMP",
                                                                 (ROOT / "tests/am4_synthetic.am4data").read_bytes()[:7868])]


def test_chat_apps_declared_in_android_manifest():
    """Android 11+ only lets the APK see the chat apps listed in <queries>."""
    from tankg import ai
    manifest = (ROOT / "android/AndroidManifest.xml").read_text(encoding="utf-8")
    for site, app in ai.CHAT_APPS.items():
        assert site in ai.WEB_SITES
        if app["android"]:
            assert f'<package android:name="{app["android"]}" />' in manifest, site


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_ui_cloud_reads_desktop_documents(tmp_path):
    """cloud.js syncs through the APK bridge and reads what tankg/cloud.py writes."""
    import json
    from tankg import cloud
    from tankg.model import Bank
    doc = cloud.make_doc(Bank.from_bytes((ROOT / "tests/live_bank.bin").read_bytes()), {"1A": "Limpio ñ"}, {"1": "Rock"},
                         amps={"3": "RANDALL Clean"}, amp_sources={"3": {"article": 7414, "file": "r.am4Data"}},
                         preset_amps={"1A": {"slot": 2, "name": "RANDALL Clean", "source": {"article": 7414, "file": "r.am4Data"}}})
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "tests/ui/cloud.test.mjs"), str(f)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout


def _tone(freq, rate, n, harmonics=(1, 0.5, 0.3, 0.2), amp=0.3):
    import math
    return [amp * sum(a * math.sin(2 * math.pi * freq * (k + 1) * i / rate + k) for k, a in enumerate(harmonics)) / 2
            for i in range(n)]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_ui_tuner_diag_and_demo_match_python(tmp_path):
    """Same tuner readings, diagnostic report/issue link and demo pedal in the APK as on the desktop."""
    import json
    import random
    from tankg import demo, diag, tuner
    random.seed(7)
    blocks = [("E2", 82.41, 48000, 440), ("A2", 110.0, 44100, 440), ("D3 bajo", 146.0, 48000, 440),
              ("G3", 196.0, 44100, 442), ("B3 alto", 248.3, 48000, 440), ("E4", 329.63, 48000, 440),
              ("A4", 440.0, 44100, 432)]
    cases = []
    for label, freq, rate, a4 in blocks:
        cases.append({"label": label, "rate": rate, "a4": a4, "samples": _tone(freq, rate, tuner.FRAME)})
    cases.append({"label": "silencio", "rate": 48000, "a4": 440, "samples": [0.0005] * tuner.FRAME})
    cases.append({"label": "ruido", "rate": 48000, "a4": 440, "samples": [random.uniform(-0.3, 0.3) for _ in range(tuner.FRAME)]})
    for c in cases:
        f = tuner.detect(c["samples"], c["rate"])
        c["freq"] = f
        c["level"] = tuner.level(c["samples"])
        if f is not None:
            n = tuner.note(f, c["a4"])
            c.update(note=f"{n['name']}{n['octave']}", cents=n["cents"], state=tuner.state(n["cents"]),
                     readings=[tuner.reading(f, t, c["a4"]) for t in range(len(tuner.TUNINGS))])
    assert [c["freq"] is None for c in cases] == [False] * len(blocks) + [True, True]
    assert [c["note"] for c in cases[:len(blocks)]] == ["E2", "A2", "D3", "G3", "B3", "E4", "A4"]
    assert [c["state"] for c in cases[:len(blocks)]] == ["ok", "ok", "low", "low", "high", "ok", "high"]

    scrub = ["Error de juan.perez+x@mail.example.com al leer", "clave sk-ant-api03-ABCDEFGHIJ inválida",
             "Traceback (most recent call last):\n  File \"x.py\", line 1\nDeviceError: sin respuesta", "", "  \n  línea 1\nlínea 2"]
    long_log = [f"12:00:{i % 60:02d} Leyendo presets ({i})" for i in range(150)]
    infos = [{"version": "1.12.0", "platform": "Linux 6.8 · Python 3.12 · Qt 6.8", "pedal": "conectada (USB)",
              "port": "Tank-G MIDI 1", "demo": False, "modified": 3, "cloud": True, "backups": 12,
              "errors": ["12:01:02 DeviceError: sin respuesta"], "log": ["12:00:00 Inicio", "12:01:02 Error: DeviceError: sin respuesta"]},
             {"version": "1.12.0", "platform": "Android 14 · WebView 130", "pedal": "desconectada", "port": "",
              "demo": True, "modified": 0, "cloud": False, "backups": 0, "errors": [], "log": []},
             {"version": "1.12.0", "platform": "Windows 11", "pedal": "conectada (Bluetooth)", "port": "TANK-Gv2_BLE",
              "errors": [], "log": long_log}]
    reports = [{"info": i, "text": diag.report(i), "url": diag.issue_url(diag.report(i))} for i in infos]
    assert "%0A%E2%80%A6" in reports[2]["url"] and len(reports[2]["url"]) < 8000   # long report cut to fit a link
    golden = {"tuner": cases, "scrub": [{"in": s, "out": diag.one_line(diag.scrub(s))} for s in scrub],
              "reports": reports}
    bank, _, _ = demo.demo_bank()
    from tankg import tempo
    taps = [[0, 0.5, 1.0, 1.5], [0, 0.5, 5, 5.4, 5.8], [1], [0, 0.0001], [0, 3], [i * 0.37 for i in range(12)],
            [0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]]
    golden["tempo"] = {"taps": [{"times": t, "bpm": tempo.tap(t)} for t in taps],
                       "bpms": [{"bpm": b, "marking": tempo.marking(b), "delays": tempo.delay_times(b),
                                 "clamped": tempo.clamp(b + 0.4)} for b in (30, 59, 60, 87.5, 120, 133, 175, 199, 200, 300)]}
    assert [c["bpm"] for c in golden["tempo"]["taps"]] == [120, 150, None, 300, None, 162, 240]
    golden["demo"] = {"banks": demo.DEMO_BANKS, "presets": [p.to_bytes().hex() for p in bank.presets]}
    gfile = tmp_path / "tools.json"
    gfile.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "tests/ui/tools.test.mjs"), str(gfile)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout

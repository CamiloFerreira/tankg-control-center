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

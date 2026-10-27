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
    from tankg import ai, artists, library
    from tankg.model import Bank, Preset
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
    preset_py = tmp_path / "p.tgpreset"
    library.save_preset(bank.presets[3], preset_py, 3, "Mi Preset ñ")
    aliases = library.Aliases(tmp_path / "a.json")
    aliases.set_preset(8, "Ocho")
    set_py = tmp_path / "s.tgset"
    library.save_set(bank, [8, 9, 10, 11], set_py, aliases, "Banco 3")
    golden = {"designs": designs, "prompts": prompts, "presetPy": preset_py.read_text(), "presetRaw": bank.presets[3].to_bytes().hex(),
              "presetName": "Mi Preset ñ", "setPy": set_py.read_text(), "setTitle": "Banco 3",
              "setRaws": [bank.presets[s].to_bytes().hex() for s in range(8, 12)], "bank": live.hex()}
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


def test_chat_apps_declared_in_android_manifest():
    """Android 11+ only lets the APK see the chat apps listed in <queries>."""
    from tankg import ai
    manifest = (ROOT / "android/AndroidManifest.xml").read_text(encoding="utf-8")
    for site, app in ai.CHAT_APPS.items():
        assert site in ai.WEB_SITES
        if app["android"]:
            assert f'<package android:name="{app["android"]}" />' in manifest, site

"""GUI flows against FakePedal: upload window, band library, undo of names, write errors and
live audition. Runs offscreen, no pedal needed."""
import os
import time
from unittest import mock

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # tests never open real windows
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from tankg import artists, dialogs, gui, library  # noqa: E402
from tankg.device import TankG  # noqa: E402
from test_tankg import LIVE, FakePedal  # noqa: E402


@pytest.fixture
def env(tmp_path):
    pedal = FakePedal(LIVE)

    def fake_open(info=None):
        dev = TankG(pedal)
        dev.bank = dev.read_bank()
        return dev

    messages = []
    patches = [mock.patch.object(gui.TankG, "open", staticmethod(fake_open)),
               mock.patch.object(gui, "find_devices", lambda *a: ["fake"]),
               mock.patch.object(dialogs, "ask", lambda *a: True),
               mock.patch.object(library, "backup", lambda bank, why: tmp_path / f"{why}.tgbank"),
               mock.patch.object(QtWidgets.QMessageBox, "information", lambda *a: messages.append(a[2])),
               mock.patch.object(QtWidgets.QMessageBox, "critical", lambda *a: messages.append(a[2]))]
    for p in patches:
        p.start()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = gui.MainWindow()
    w.timer.stop()
    w.aliases = library.Aliases(tmp_path / "aliases.json")

    def wait(cond, timeout=5.0):
        end = time.monotonic() + timeout
        while not cond() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
        return cond()

    assert wait(lambda: w.device is not None and not w.busy)
    yield w, pedal, wait, messages
    w.live_timer.stop()
    w._cloud_started = True   # its delayed startup sync must not run during later tests
    w.cloud_timer.stop()
    for d in app.topLevelWidgets():
        d.close()
    for p in patches:
        p.stop()


def mem(pedal, slot):
    return bytes(pedal.mem[2 + 21 * slot: 2 + 21 * (slot + 1)])


def uploads(w):
    return [d for d in w.findChildren(dialogs.UploadDialog) if d.isVisible()]


def test_single_preset_upload_window(env):
    w, pedal, wait, _ = env
    p = w.local.presets[0].copy()
    p.set("gain", 33)
    w._set_local(0, p)
    w.send_selected()
    assert len(uploads(w)) == 1
    assert wait(lambda: not w.busy) and mem(pedal, 0) == p.to_bytes()
    assert not w.modified_slots()
    assert wait(lambda: not uploads(w), 3)   # closes by itself after a verified write


def test_library_bank_uploads_and_undo_restores_names(env):
    w, pedal, wait, _ = env
    lib = dialogs.ArtistLibrary(w)
    lib.list.setCurrentRow(next(i for i, b in enumerate(lib.banks) if b and b.name == "Blind Guardian"))
    lib.dest.setCurrentIndex(1)
    lib.apply_bank()
    assert wait(lambda: not w.busy)
    assert all(mem(pedal, s) == w.local.presets[s].to_bytes() for s in range(4, 8))
    assert w.aliases.preset(4) == "Guardian Limpio" and w.aliases.bank(1) == "Blind Guardian"
    assert w.device.presets[7].color == artists.ROLE_COLORS["Solo"]
    w.undo()
    assert w.aliases.preset(4) == "" and w.aliases.bank(1) == ""
    assert set(w.modified_slots()) == {4, 5, 6, 7}


def test_ai_bank_uploads_once(env):
    w, pedal, wait, _ = env
    items = [(s.build(w.local.presets[8 + i]), s.name, "") for i, s in enumerate(artists.BANKS[10].presets)]
    w.apply_generated_bank(2, "IA", items)
    assert wait(lambda: not w.busy)
    assert all(mem(pedal, s) == w.local.presets[s].to_bytes() for s in range(8, 12))
    wait(lambda: not uploads(w), 3)
    w.apply_generated_bank(2, "IA", items)   # identical: nothing to send
    assert not w.busy and not uploads(w)


def test_write_error_stays_in_upload_window(env):
    w, pedal, wait, messages = env
    pedal.drop_writes = True
    p = w.local.presets[1].copy()
    p.set("gain", 77)
    w._set_local(1, p)
    w.current = 1
    w.send_selected()
    assert wait(lambda: not w.busy)
    (dialog,) = uploads(w)
    assert not dialog.running and dialog.close_btn.isEnabled()
    assert not messages and w.modified_slots() == [1]


def test_upload_window_ignores_escape_while_running(env):
    w, *_ = env
    d = dialogs.UploadDialog(w, [0], ["x"])
    d.show()
    d.reject()
    assert d.isVisible()
    d.failed("error")
    d.reject()
    assert not d.isVisible()


def test_live_off_cancels_pending_write(env):
    w, pedal, wait, _ = env
    w.live_action.setChecked(True)
    w.current = 2
    p = w.local.presets[2].copy()
    p.set("treble", 99)
    w._set_local(2, p)
    assert wait(lambda: mem(pedal, 2) == p.to_bytes(), 3)
    assert wait(lambda: not w.busy)
    p = p.copy()
    p.set("treble", 40)
    w._set_local(2, p)   # starts the debounce timer
    w.live_action.setChecked(False)
    wait(lambda: False, 1.0)
    assert mem(pedal, 2) != p.to_bytes() and not w.busy


def test_library_offline_keeps_changes_in_editor(env):
    w, _, _, _ = env
    w.connected = False
    w.current = 3
    lib = dialogs.ArtistLibrary(w)
    assert not lib.upload.isEnabled()
    lib.apply_one()
    assert not w.busy and 3 in w.modified_slots() and not uploads(w)
    lib = dialogs.ArtistLibrary(w)
    lib.search.setText("zzzz")
    assert not lib.one_btn.isEnabled() and not lib.bank_btn.isEnabled()


def test_qt_platform_falls_back_to_wayland_when_xcb_cannot_start(monkeypatch, tmp_path):
    """Flameshot sets QT_QPA_PLATFORM=xcb; without libxcb-cursor X11 aborts, so use Wayland."""
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    monkeypatch.setattr(gui, "_xcb_cursor_available", lambda: False)
    gui._choose_qt_platform()
    assert os.environ["QT_QPA_PLATFORM"] == "wayland"
    monkeypatch.setenv("QT_QPA_PLATFORM", "xcb")
    monkeypatch.setattr(gui, "_xcb_cursor_available", lambda: True)   # bundled in the executable
    gui._choose_qt_platform()
    assert os.environ["QT_QPA_PLATFORM"] == "xcb"
    os.environ["QT_QPA_PLATFORM"] = "offscreen"   # keep the other tests headless


def test_cloud_autosync_edits_and_loads_newer_at_start(env, tmp_path, monkeypatch):
    import json
    from test_tankg import FakeGoogle
    from tankg import cloud
    w, pedal, wait, messages = env
    google = FakeGoogle()
    monkeypatch.setattr(cloud, "_request", google)
    monkeypatch.setattr(cloud, "CLIENT_ID", "id")
    monkeypatch.setattr(cloud, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(library, "SETTINGS_FILE", tmp_path / "settings.json")
    library.Settings().set_cloud({"refresh_token": "r"})
    w._cloud_started = w._cloud_ready = False
    w.cloud_startup()   # empty cloud: this device starts it
    assert wait(lambda: len(google.files) == 1 and not w._bg and "guardados" in w.cloud_label.text(), 8)
    w.cloud_label.clear()
    # any edit in the editor goes up by itself a moment later, without saving to the pedal
    p = w.local.presets[0].copy()
    p.set("gain", 21)
    w._set_local(0, p)
    w.aliases.set_preset(0, "Desde Linux")
    w.aliases.set_bank(0, "Banco Linux")
    w.refresh()
    assert wait(lambda: "guardados" in w.cloud_label.text(), 8)
    doc = json.loads(next(f for f in google.files.values() if f["name"] == cloud.LATEST)["body"])
    assert bytes.fromhex(doc["bank"])[2:23] == p.to_bytes()
    assert doc["aliases"]["presets"]["1A"] == "Desde Linux" and doc["aliases"]["banks"]["1"] == "Banco Linux"
    assert w.modified_slots() == [0]   # the pedal is untouched
    # another device (the phone) saves a newer version; the next start loads it without asking
    other = w.device.copy()
    other.presets[1].set("gain", 99)
    newer = cloud.make_doc(other, {"1B": "Desde Android"}, {"2": "Banco Android"}, "Android · moto", amps={"3": "RANDALL"})
    next(f for f in google.files.values() if f["name"] == cloud.LATEST)["body"] = json.dumps(newer).encode()
    w._cloud_started = w._cloud_ready = False
    w.cloud_startup()
    assert wait(lambda: not w._bg and w._cloud_ready)
    assert w.local.presets[1].get("gain") == 99 and w.aliases.preset(1) == "Desde Android"
    assert w.aliases.bank(1) == "Banco Android" and w.aliases.amp(2) == "RANDALL"
    assert w.controls["amp_type"].combo.itemText(2) == "3. RANDALL"
    assert set(w.modified_slots()) >= {1} and not messages   # in the editor only, until «Guardar cambios»
    assert library.Settings().cloud["synced"] == cloud.doc_key(newer)


@pytest.mark.parametrize("which", ["factory", "amp"])
def test_amp_cab_windows_close_after_bluetooth_not_found(env, which):
    """Without a Bluetooth pedal the job fails; the window shows the error and can be closed."""
    w, _, wait, messages = env
    from tankg.device import DeviceError

    def no_bluetooth():
        raise DeviceError("No se encontró la Tank-G por Bluetooth.")

    with mock.patch.object(gui.TankG, "open_bluetooth", staticmethod(no_bluetooth)):
        if which == "factory":
            d = dialogs.FactoryAmpCabDialog(w)
        else:
            d = dialogs.AmpUploadDialog(w, (__import__("pathlib").Path(__file__).parent / "am4_synthetic.am4data").read_bytes(), "X")
        d.show()
        d._start()
        d.reject()                       # ignored while the job runs
        assert d.isVisible()
        assert wait(lambda: not w.busy)
    assert not d.running and d.close_btn.isEnabled() and d.go.isEnabled()
    assert "Bluetooth" in d.step.text() and not messages
    d.reject()
    assert not d.isVisible()


def test_command_menu_covers_every_command_and_searches(env):
    from tankg import menu
    w, *_ = env
    actions = w.command_actions()
    assert {cmd for _, cmd, *_ in menu.items()} == set(actions)   # every desktop entry runs something
    assert {"view", "demo"} == {cmd for _, entries in [(g[0], g[2]) for g in menu.MENU] for cmd, *_ in entries} - set(actions)
    ran = []
    with mock.patch.object(w, "command_actions", lambda: {c: (lambda c=c: ran.append(c)) for c in actions}):
        d = dialogs.CommandMenu(w)
        d.show()
        d.search.setText("fabrica amp")   # accents are ignored, every word must match
        visible = [c for row, c, _ in d.rows if row.isVisible()]
        assert visible == ["ampUpload", "factoryAmpCab"] and d.quick.isHidden()
        d.search.returnPressed.emit()
        _, _, wait, _ = env
        assert wait(lambda: ran == ["ampUpload"]) and not d.isVisible()
    d = dialogs.CommandMenu(w)
    rows = {c: row for row, c, _ in d.rows}
    assert not rows["paste"].isEnabled()                                         # nothing copied yet
    assert rows["cloudConnect"].property("available") and not rows["cloudPush"].property("available")

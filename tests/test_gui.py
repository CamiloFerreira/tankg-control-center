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
from tankg.model import Bank  # noqa: E402
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
    # offline: a change that never reached the cloud survives closing the app and goes up at the next start
    monkeypatch.setattr(cloud, "push", lambda *a: (_ for _ in ()).throw(cloud.CloudError("sin red")))
    w.aliases.set_preset(2, "Hecho sin red")
    w.aliases.setlists.append({"title": "Show offline", "songs": []})
    w.refresh()
    assert wait(lambda: "se reintentará" in w.cloud_label.text(), 8)
    assert library.Settings().cloud["pending"]["aliases"]["presets"]["1C"] == "Hecho sin red"
    monkeypatch.undo()   # the network is back
    monkeypatch.setattr(cloud, "_request", google)
    monkeypatch.setattr(cloud, "CLIENT_ID", "id")
    monkeypatch.setattr(cloud, "CLIENT_SECRET", "secret")
    monkeypatch.setattr(library, "SETTINGS_FILE", tmp_path / "settings.json")
    w.aliases.presets.pop("1C")          # the next start: names as the pedal-read editor had them
    w.aliases.setlists.clear()
    w._cloud_started = w._cloud_ready = False
    w.cloud_startup()
    assert wait(lambda: "guardados" in w.cloud_label.text(), 8)
    assert w.aliases.preset(2) == "Hecho sin red" and w.aliases.setlists[0]["title"] == "Show offline" and not messages
    latest = json.loads(next(f for f in google.files.values() if f["name"] == cloud.LATEST)["body"])
    assert latest["aliases"]["presets"]["1C"] == "Hecho sin red" and "pending" not in library.Settings().cloud
    # both changed (another device saved meanwhile): asks, and «Los de la nube» keeps a backup of this one
    library.Settings().set_cloud({**library.Settings().cloud, "pending": w._cloud_doc() | {"bank": other.to_bytes().hex()}})
    phone = cloud.make_doc(w.device, {"1A": "Del teléfono"}, {}, "Android · moto")
    next(f for f in google.files.values() if f["name"] == cloud.LATEST)["body"] = json.dumps(phone).encode()
    backups = []
    with mock.patch.object(dialogs, "choose", lambda *a: False), \
            mock.patch.object(library, "backup", lambda bank, why: backups.append(why)):
        w._cloud_started = w._cloud_ready = False
        w.cloud_startup()
        assert wait(lambda: not w._bg and w._cloud_ready)
    assert w.aliases.preset(0) == "Del teléfono" and backups == ["sin-subir"]


def test_cloud_startup_rule():
    from tankg import cloud
    table = {("C", "C", "S", None): "same", ("C", "L", "S", None): "cloud", (None, "L", None, None): "local",
             ("S", "L", "S", "P"): "local", (None, "L", "S", "P"): "local", ("C", "L", "S", "P"): "conflict",
             ("P", "L", "S", "P"): "same"}
    assert {k: cloud.startup_action(*k) for k in table} == table


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
        visible = [c for row, c, _ in d.rows if not row.isHidden()]
        assert visible == ["ampUpload", "factoryAmpCab"] and d.quick.isHidden()
        d.search.returnPressed.emit()
        _, _, wait, _ = env
        assert wait(lambda: ran == ["ampUpload"]) and d.isHidden() and w.command_menu is None
    w.toggle_menu()   # «☰ Menú» opens the panel inside the window and closes it again
    d = w.command_menu
    assert d is not None and d.parent() is w and not w.menuBar().isVisible()
    rows = {c: row for row, c, _ in d.rows}
    assert not rows["paste"].isEnabled()                                         # nothing copied yet
    assert rows["cloudConnect"].property("available") and not rows["cloudPush"].property("available")
    w.toggle_menu()
    assert w.command_menu is None


def test_pack_import_uploads_models_then_presets(env, tmp_path):
    """A bank pack with one AMP model: the model goes to the chosen slot over Bluetooth, the presets
    that used it are remapped, then written and verified; names and the model copy are kept."""
    from tankg import pack
    from tankg.device import TankGBle
    from test_tankg import AM4_FIXTURE, FakeBlePedal
    w, _, wait, messages = env
    src = w.local.copy()
    src.presets[0].raw[5] = 2
    doc, _ = pack.make(src, [0, 1, 2, 3], {0: "Con AMP"}, {"1": "Pack"}, {"3": "Mi AMP"}, {2: AM4_FIXTURE[:7868]}, "Pack")
    loaded = pack.parse(doc)
    ble = FakeBlePedal(LIVE)

    def open_ble():
        dev = TankGBle(ble)
        dev.bank = dev.read_bank()
        return dev

    store_dir = tmp_path / "amps"
    with mock.patch.object(gui.TankG, "open_bluetooth", staticmethod(open_ble)), \
            mock.patch.object(library.ModelStore, "__init__", lambda self, folder=None: setattr(self, "folder", store_dir)):
        d = dialogs.PackImportDialog(w, loaded)
        d.show()
        d.dest.setCurrentIndex(2)            # bank 3
        d.amp_slots[0].setCurrentIndex(5)    # the model to AMP 6 instead of 3
        d._start()
        assert wait(lambda: not w.busy, 10)
        assert not d.running and "importado" in d.step.text() and not messages
        assert ble.amps == {5: AM4_FIXTURE}                       # uploaded with its LMT block, to slot 6
        written = Bank.from_bytes(bytes(ble.mem))
        assert written.presets[8].amp == 5                        # remapped: AMP 3 -> 6
        assert [written.presets[8 + i].to_bytes()[6:] for i in range(1, 4)] == [src.presets[i].to_bytes()[6:] for i in range(1, 4)]
        assert w.aliases.amp(5) == "Mi AMP" and w.aliases.preset(8) == "Con AMP" and w.aliases.bank(2) == "Pack"
        assert library.ModelStore().get(5) == AM4_FIXTURE[:7868]
        assert w.controls["amp_type"].combo.itemText(5) == "6. Mi AMP"


def test_band_pack_import_downloads_its_models(env):
    """A band pack (references only): the window lists the authors, asks to download what is missing,
    then uploads the downloaded models and the presets."""
    from tankg import pack
    from tankg.device import TankGBle
    from test_tankg import AM4_FIXTURE, FakeBlePedal
    w, _, wait, messages = env
    _, loaded = pack.builtin()[0]
    ble = FakeBlePedal(LIVE)

    def open_ble():
        dev = TankGBle(ble)
        dev.bank = dev.read_bank()
        return dev

    asked = []
    with mock.patch.object(gui.TankG, "open_bluetooth", staticmethod(open_ble)), \
            mock.patch.object(pack, "fetch", lambda amp: AM4_FIXTURE[:7868]), \
            mock.patch.object(dialogs, "ask", lambda parent, title, text: asked.append(text) or True):
        d = dialogs.PackImportDialog(w, loaded)
        assert any(a.credit["author"] in lbl.text() for a in loaded.amps for lbl in d.findChildren(QtWidgets.QLabel))
        d.show()
        d._start()
        assert wait(lambda: not w.busy, 60) and "importado" in d.step.text() and not messages   # LMT ~5 s per model
    assert "descargarlos" in asked[0].lower()                     # missing models: asked before downloading
    assert set(ble.amps) == {a.slot for a in loaded.amps}
    assert w.aliases.amp(loaded.amps[0].slot) == loaded.amps[0].name


def test_pack_preset_warns_when_its_amp_is_replaced(env):
    """After a band pack import, replacing that TYPE with another model makes the editor warn on the
    pack presets; the confirmation of an upload counts the presets that will sound different."""
    w, *_ = env
    w.local.presets[8].raw[5] = 8
    w.aliases.set_amp(8, "Randall", {"article": 7414, "file": "x.am4Data"})
    w.aliases.set_preset_amp(8, {"slot": 8, "name": "Randall", "source": {"article": 7414, "file": "x.am4Data"}})
    w.current = 8
    w.refresh()
    assert w.amp_warn.isHidden()
    w.aliases.set_amp(8, "Otro")
    w.refresh()
    assert not w.amp_warn.isHidden() and "Randall" in w.amp_warn.text() and "Otro" in w.amp_warn.text()
    warning = w.replace_warning([8])
    assert "3A" in warning and "TYPE 9" in warning
    assert "3A" not in w.replace_warning([8], exclude=[8])


def test_cloud_version_offers_missing_community_models(env):
    """A cloud version made on another device with community models: this device offers to download
    the ones it lacks and keeps them (to export packs or upload them again)."""
    from tankg import cloud, pack
    from test_tankg import AM4_FIXTURE
    w, _, wait, _ = env
    library.ModelStore().clear()   # earlier tests may have kept models in the shared temporary data folder
    doc = cloud.make_doc(w.local, {}, {}, amps={"9": "Randall"}, amp_sources={"9": {"article": 7414, "file": "r.am4Data"}})
    asked = []
    with mock.patch.object(dialogs, "ask", lambda parent, title, text: asked.append(text) or True), \
            mock.patch.object(pack, "fetch", lambda amp: AM4_FIXTURE[:7868]):
        w.load_cloud(doc)
        assert wait(lambda: library.ModelStore().get(8) is not None)
    assert "Randall" in asked[0] and w.aliases.amp_sources == {"9": {"article": 7414, "file": "r.am4Data"}}


def test_factory_restore_names_presets_and_whole_banks(env):
    w, pedal, wait, messages = env
    names = library.factory_names("original")
    w._factory_names([0, 1, 2, 3, 4], "original")
    assert w.aliases.preset(0) == names["presets"]["1A"] and w.aliases.preset(4) == names["presets"]["2A"]
    assert w.aliases.bank(0) == names["banks"]["1"] and w.aliases.bank(1) == ""   # bank 2 only partly restored


def test_setlists_saved_ordered_and_stage_mode(env):
    w, pedal, wait, _ = env
    w.aliases.set_preset(10, "Thunderstruck")
    before = w.local.copy()
    d = dialogs.SetlistDialog(w)
    for s in (10, 0, 30):
        d.pool.setCurrentRow(s)
        d.add()
    d.songs.setCurrentRow(2)
    d.move(-1)                      # 30 before 0
    d.songs.setCurrentRow(0)
    d._note_edited("afinación drop D")
    d.title.setText("Bar")
    d._renamed("Bar")
    d.start.setCurrentIndex(d.start.findData(4))
    d.copy_text()
    assert QtWidgets.QApplication.clipboard().text().splitlines()[2:] == [
        " 1. 3C  Thunderstruck  (afinación drop D)", f" 2. 8C  {before.presets[30].amp_name}",
        f" 3. 1A  {before.presets[0].amp_name}"]
    assert library.Aliases(w.aliases.path).setlists[0]["title"] == "Bar"   # saved as it is edited
    d.apply()
    assert [w.local.presets[s] for s in (4, 5, 6)] == [before.presets[s] for s in (10, 30, 0)]
    assert w.aliases.preset(4) == "Thunderstruck" and d.slots == [4, 5, 6]
    assert [s["slot"] for s in w.aliases.setlists[0]["songs"]] == ["2A", "2B", "2C"]
    d.new()
    assert len(w.aliases.setlists) == 2 and d.songs.count() == 0
    d.pick.setCurrentIndex(0)
    assert d.songs.count() == 3
    stage = dialogs.StageWindow(w, "Bar", d.current()["songs"], d.slots)
    assert stage.name.text() == "Thunderstruck" and stage.note.text() == "afinación drop D" and w.current == 4
    stage.go(1)
    assert stage.slot.text() == "2B" and w.current == 5 and stage.up_next.text() == f"2C · {before.presets[0].amp_name}"
    assert wait(lambda: b"\xc0\x05" in pedal.sent)   # Program Change: the pedal plays the song
    stage.go(5)                     # past the end: stays
    assert stage.pos == 1
    stage.close()
    w.undo()
    assert w.local.to_bytes() == before.to_bytes() and w.aliases.preset(10) == "Thunderstruck"
    assert len(w.aliases.setlists) == 2   # setlists are not editor changes


def test_library_cards(env):
    w, *_ = env
    lib = dialogs.ArtistLibrary(w)
    cards = [lib.list.item(i).data(dialogs.CARD_ROLE) for i in range(lib.list.count())]
    assert cards[0] == {"header": "BÁSICOS"} and cards[1]["badge"] == "GE" and len(cards[1]["pips"]) == 4
    assert lib.presets.count() == 4 and lib.presets.item(0).data(dialogs.CARD_ROLE)["badge"] == "A"
    lib.presets.setCurrentRow(3)
    assert lib.detail.text() == lib._bank().presets[3].summary()
    assert [dialogs.initials(n) for n in ("Blind Guardian", "AC/DC", "★ Pantera", "")] == ["BG", "AC", "PA", "?"]


def test_saved_bluetooth_pedal_counts_only_when_it_answers(env, tmp_path, monkeypatch):
    from tankg import cloud
    from tankg.device import DeviceError, DeviceInfo
    w, pedal, wait, messages = env
    ble = [DeviceInfo("ble", "Tank-G (Bluetooth)", "73:E0:23:DA:C1:2A")]
    away = mock.patch.object(gui.TankG, "open", staticmethod(lambda info=None: (_ for _ in ()).throw(DeviceError("no responde"))))
    with mock.patch.object(gui, "find_devices", lambda *a: ble), away:
        w._ble_ok, w._ble_try = False, -1e9
        w._poll_device()                       # tries it quietly once…
        assert not w.connected and wait(lambda: not w.busy)
        w._poll_device()                       # …and not again right away
        assert not w.connected and not w.busy and "desconectada" in w.conn.text() and not messages
    with mock.patch.object(gui, "find_devices", lambda *a: ble):
        w._ble_try = -1e9
        w._poll_device()                       # now it answers
        assert wait(lambda: w._ble_ok and not w.busy)
        w._poll_device()
        assert w.connected and "conectada" in w.conn.text()
    # without the pedal nothing goes up to the cloud: it waits as pending
    monkeypatch.setattr(library, "SETTINGS_FILE", tmp_path / "settings.json")
    library.Settings().set_cloud({"refresh_token": "r", "synced": "x"})
    pushed = []
    monkeypatch.setattr(cloud, "push", lambda drive, doc: pushed.append(doc))
    w.connected, w._cloud_ready = False, True
    w._cloud_autopush()
    assert not pushed and "pending" in library.Settings().cloud and "Sin pedalera" in w.cloud_label.text()
    w.connected = True
    w._cloud_autopush()
    assert wait(lambda: pushed and not w._cloud_busy)


def test_editor_opens_last_backup_without_pedal(env, tmp_path, monkeypatch):
    w, pedal, wait, _ = env
    other = w.device.copy()
    other.presets[0].set("gain", 7)
    path = tmp_path / "bank-20261029-120000-auto.tgbank"
    path.write_bytes(other.to_bytes())
    monkeypatch.setattr(library, "list_backups", lambda: [path])
    w.local = w.device = None
    w.connected = False
    w._offline_editor()
    assert w.local.presets[0].get("gain") == 7 and w.device is None
    w.connected = True
    w.read_device()                            # untouched: the pedal replaces it
    assert wait(lambda: not w.busy) and w.local.to_bytes() == w.device.to_bytes()

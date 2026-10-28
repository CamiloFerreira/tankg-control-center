# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Preset manager for the M-VAVE Tank-G guitar pedal: Linux/Windows (PySide6 GUI + CLI, `tankg/`) and an Android APK (`android/`). It speaks the reverse-engineered protocol of the official M-EFCS editor over USB-MIDI (SysEx) and, for the Tank-G v2, over Bluetooth LE (`tankg/bleproto.py`). Only these three targets exist: there is no web/browser version. User-facing text (UI, CLI, docs) is in Spanish.

## Commands

```bash
./run.sh                    # GUI (creates .venv on first run; forces Qt Wayland backend when libxcb-cursor0 is missing)
./run.sh list               # CLI: any argument switches to tankg/cli.py (list, backup, restore, diff, export, import, copy, swap, set, reset, select, info)
.venv/bin/python -m pytest -q                                 # all tests (no pedal needed)
.venv/bin/python -m pytest -q tests/test_tankg.py::test_golden_frames   # single test
.venv/bin/python -m pyflakes tankg/                           # lint
QT_QPA_PLATFORM=offscreen .venv/bin/python -c "from PySide6.QtWidgets import QApplication; from tankg import gui; app=QApplication([]); gui.MainWindow()"   # GUI smoke test
python3 tools/probe_read.py FIELD LENGTH SPACE              # read-only raw SysEx probe against the pedal
```

Windows: `run.bat` (same behaviour). CI (`.github/workflows/tests.yml`) runs pytest + the offscreen GUI smoke test on ubuntu and windows.

Executable: `.venv/bin/python packaging/build.py` (PyInstaller one-file → `dist/TankG`, `dist\TankG.exe` on Windows; bundles the factory bank and icon, found at runtime through `library.PROJECT_ROOT` = `sys._MEIPASS`). `packaging/install-linux.sh` installs it with a .desktop entry. Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds both and publishes a GitHub release with `packaging/RELEASE_NOTES.md`. Brand icon: `packaging/icon.svg` is the only source; `packaging/make_icon.py` renders icon.png/.ico, the Android mipmaps, `docs/img/logo.png` and copies it to `android/ui/img/icon.svg`.

## Architecture

Layers, bottom-up (all in `tankg/`):

- `sysex.py` — frame codec: `F0 00 32 | CLS | CMD(4) | 02 | FIELD(4) | SUB(4) | pack7(payload+ck8) | F7`. CMD/FIELD/SUB are 7-bit little-endian u32; `SUB = len<<4 | space`; checksum covers payload + FIELD + SUB bytes. A frame with a bad checksum is silently ignored by the pedal.
- `model.py` — the bank: `A5 5A` + 36 records × 21 bytes (758 bytes), slots `1A..9D` (`slot = (bank-1)*4 + letter`). `FIELDS` maps each byte to a front-panel control; only `amp_type` (byte 5) and `cab` (byte 17) are verified, the rest is inferred from the manual (`verified=False`). Bytes 18–20 are the footswitch LED colour (RGB, inferred). Unknown bytes must round-trip untouched.
- `device.py` — transports + protocol. `find_devices()` prefers ALSA rawmidi on Linux (`/proc/asound/card*/usbid == 4c4a:c755`, `/dev/snd/midiC*D0`, zero deps) and falls back to python-rtmidi (Windows/macOS), matching the port name "USB Composite Device". `TankG.open()` identifies the model by reading the bank (VID:PID is a generic Jieli id shared with other M-VAVE pedals). `write_presets()` writes each changed record (`CLS 09`, `CMD 0x41 + 8*21`, space 0, field `2 + 21*slot`), waits for the ACK, sends COMMIT (space F), then re-reads and verifies. `select_preset()` is MIDI Program Change 0–35 on channel 1.
- `library.py` — files and per-user data: `.tgbank` (raw 758 bytes, same as M-EFCS `tankG_*_preset.bin`), `.tgpreset`/`.tgset` (JSON with hex `raw` + interface names), automatic backups, `Aliases` (preset/bank names: the pedal stores no names, so they live only in `aliases.json`). Data dir: `~/.local/share/tankg` or `%APPDATA%\tankg`.
- `artists.py` — band/style presets (`BANKS`: banks of 4 `StylePreset`s written as AI designs, built with `ai.apply_design`); shown by `dialogs.ArtistLibrary`.
- `cloud.py` — Google Drive sync (scope drive.file, folder "Tank-G Control Center"): `tankg-cloud.json` + `tankg-history-*.json` (30 kept). Sign-in is Google's device flow on all three platforms (code + google.com/device; the device flow rejects drive.appdata). One OAuth client ("TVs and Limited Input devices"), read by `cloud_config.py` from `tankg/cloud_secrets.json` = the JSON downloaded from the Google console. **Never commit it**: it is git-ignored, bundled by `packaging/build.py`, written into the APK as `js/secrets.js` by `android/build.sh`, and created in CI from the `TANKG_CLOUD_SECRETS` secret; without it the feature is disabled. Versions are identified by `doc_key` (content hash), not by time.
- `ai.py` — LLM preset generation over plain urllib (Claude Messages API with a forced tool, OpenAI/compatible `chat/completions` with a JSON schema). The model returns a "design" (effect type + 0–100 amount for the three-zone knobs); `apply_design()` maps it to bytes, keeping unmapped bytes from the current preset. The system prompt carries the AMP/CAB descriptions from the official preset list.
- `theme.py` — the single stylesheet (colour tokens + shared rules). `gui.STYLE` only adds pedal-panel rules (`theme.QSS + gui.STYLE`). Secondary windows subclass `dialogs.StyledDialog` (header, numbered `card()`s, footer `button()`s) and style widgets only through objectNames (`primary`, `secondary`, `link`, `chip`, `seg`, `modeCard`); use `dialogs.ask()` for yes/no questions.
- `gui.py` / `dialogs.py` — `MainWindow` keeps two banks: `device` (last read from the pedal) and `local` (working copy); "modified" = slots where they differ. Every pedal operation runs in a `Job` (QRunnable) that opens the device, does the work and closes it, so other apps keep MIDI access. Jobs must stay referenced in `self._jobs` until they report back (otherwise their signals are garbage-collected). Edits go through `_set_local()` (undo stack + optional live audition, which writes and re-selects the preset after a debounce). Writes go through `_send()`, which shows `dialogs.UploadDialog` (per-slot progress via `report(text, n, total)`); `apply_presets()` (AI results, band presets) uploads right away when the pedal is connected.

## Android app

- `android/ui/` — the APK's interface (plain ES modules, no build step; it only runs inside the APK): `js/protocol.js` is a 1:1 port of `sysex.py` + `TankG` and of `bleproto.py` + `TankGBle` (golden frames checked by `tests/ui/protocol.test.mjs`), `js/data.js` is generated by `tools/export_ui.py` (`tests/test_ui.py` fails when stale), `js/app.js` is the UI. Layout: phone vs `.tablet` (min-width 760 and min-height 560, or forced from the menu); inside tablet the pedal adapts with a container query.
- `android/` — APK = WebView serving `android/ui` from `https://appassets.androidplatform.net` + `MainActivity.java` bridge (`window.AndroidMidi`): USB MIDI via `android.media.midi` (list/open/send/close; callbacks `__midiIn`, `__midiState`, `__midiOpened`), Bluetooth LE via `Ble.java` (blePedals/bleOpen/bleSend/bleClose; `__bleIn`, `__bleState`), files, HTTP for the AI, updates. Built by `android/build.sh` without Gradle (build-tools 35: d8 34 crashes on JDK 21 classes). Debug builds enable WebView remote debugging for testing over adb.
- Bluetooth: the APK connects by itself at startup (USB first, then bonded pedals; retried every 15 s). Android keeps a closed link ~1 s, so `Ble.java` waits 2 s before reconnecting. Desktop uses bleak (`BleLink` in `device.py`); BlueZ exposes the pedal's BLE-MIDI as an ALSA port that ignores SysEx, so `_port_score` skips "Bluetooth" ports.

## Three platforms, one app (keep them in sync)

Windows/Linux (`tankg/`, PySide6) and Android (`android/`) are the same product. **Every user-facing change goes to both in the same commit**; nothing is "desktop only" unless it cannot exist on the other side (CLI, live MIDI port names on Windows). Checklist for any change:

1. Shared data lives in Python and is generated for the APK: version (`tankg/version.py`), field map, model names, band library (`tankg/artists.py`), factory bank, AI prompt/schemas/suggestions (`tankg/ai.py`). After touching any of them run `.venv/bin/python tools/export_ui.py` (`tests/test_ui.py` fails while `android/ui/js/data.js` is stale).
2. Logic that exists twice must behave identically and is tested against each other: SysEx/`TankG` and Bluetooth/`TankGBle` (`protocol.js` vs `sysex.py`/`bleproto.py`/`device.py`, golden frames captured from the pedal and the official app), `apply_design`/browser prompt/answer parsing (`ai.js` vs `ai.py`), `.tgbank/.tgpreset/.tgset` (`files.js` vs `library.py`, files written by one are loaded by the other in `test_ui_ai_and_files_match_python`).
3. UI features: desktop menu/toolbar/right-click ↔ APK menu sheet (`run(cmd)` in `app.js`), long-press preset menu, `dialogs.*` ↔ sheets in `index.html`. The table below must stay complete.
4. Run `pytest` (desktop + JS through node), build `android/build.sh debug` and try it on a phone when the change touches the UI or the pedal.
5. Bump `tankg/version.py` for a release; the tag must be `v<version>` (checked by the release workflow). Releases are mirrored to the public `RELEASES_REPO`, from which all three apps update themselves (`tankg/updater.py`, `checkUpdate()` in `app.js` + `installUpdate` in `MainActivity`). Without the `RELEASES_TOKEN` secret, run `tools/publish_release.sh vX.Y.Z` after the release workflow.

| Feature | Desktop | Android |
|---|---|---|
| Read / save all / save one / activate | toolbar, Pedalera menu | toolbar (tablet), bottom bar, menu, footswitches |
| Live audition | toolbar toggle | menu → Escucha en vivo |
| Backups (auto, manual, manager, restore file) | Pedalera menu, `BackupManager` | menu → backups sheet, download `.tgbank` |
| MIDI port / Bluetooth pedal choice | `MidiPortDialog` (scan with bleak) | port sheet (bonded pedals) |
| Calibration wizard | `CalibrationWizard` | calibration sheet |
| Undo, copy/paste, duplicate, swap, move | Editar menu, right click | menu, long press |
| Preset / bank names, LED colour | alias field, bank head, LED button | alias field, bank tag, LED button |
| Band library | `ArtistLibrary` | library sheet |
| AI (browser + API keys) | `AIDialog` | AI sheet (`ai.js`; native HTTP bridge in the APK) |
| Factory restore (preset/bank/all), revert | Editar menu | menu |
| Files: open/save bank, import/export preset and set, compare | Archivo menu | menu (file picker / Downloads) |
| Bytes of the preset, about, updates | Ayuda menu | menu |
| AMP model upload, factory AMP/CAB restore (AM4/AM3, Bluetooth) | Pedalera menu, `AmpUploadDialog`, `FactoryAmpCabDialog` | menu |
| Google Drive sync (auto push after a verified save, offer newer version at start, history) | Nube menu (`tankg/cloud.py`, `dialogs.CloudSignIn` code) | menu → Nube (`cloud.js`, device-flow code) |

## Protocol facts and rules

- Verified on hardware: bank read (space 0, len 758), single-record write + commit (persists across power cycle), Program Change select. Spaces 1/2 of the MK-300 protocol do not exist on the Tank-G (they echo a stale buffer).
- AMP model upload (`.am4data`, `tankg/am4.py` computes the LMT block bit-exact) and factory AMP/CAB restore (sets AM4/AM3, images in `research/factory/` and `android/ui/factory/`) are captured from M-EFCS over Bluetooth only (`research/FINDINGS.md` §9); USB raises an error.
- Not implemented on purpose (protocol unverified, could overwrite factory data): IR/CAB import (WAV→CAB conversion unknown), Loopback and other global settings, firmware update.
- `research/FINDINGS.md` is the source of truth for what is verified vs inferred; mark anything new accordingly and never invent commands or byte meanings. The calibration assistant (`dialogs.CalibrationWizard`) exists to confirm the inferred field map.
- Before writing to the pedal, take a backup (`library.backup`); write only changed slots and verify by read-back.
- Three-zone knobs (MOD FX, DLY MIX, RVB DECAY) select one of three effect types by position; zone limits are assumed equal thirds (unverified).
- `tests/live_bank.bin` is a real bank image used as a fixture; golden frames in tests are captures from the real pedal — do not "fix" them to match the code.
- `research/factory/`, `android/ui/factory/` and `research/TANK-G_en.pdf` are M-VAVE files extracted from M-EFCS; fine in the private repo, remove before making it public.

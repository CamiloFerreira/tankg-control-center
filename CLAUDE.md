# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Preset manager (PySide6 GUI + CLI) for the M-VAVE Tank-G guitar pedal on Linux and Windows. It speaks the reverse-engineered SysEx protocol of the official M-EFCS editor over USB-MIDI. User-facing text (UI, CLI, docs) is in Spanish.

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

Executable: `.venv/bin/python packaging/build.py` (PyInstaller one-file → `dist/TankG`, `dist\TankG.exe` on Windows; bundles the factory bank and icon, found at runtime through `library.PROJECT_ROOT` = `sys._MEIPASS`). `packaging/install-linux.sh` installs it with a .desktop entry. Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds both and publishes a GitHub release with `packaging/RELEASE_NOTES.md`.

## Architecture

Layers, bottom-up (all in `tankg/`):

- `sysex.py` — frame codec: `F0 00 32 | CLS | CMD(4) | 02 | FIELD(4) | SUB(4) | pack7(payload+ck8) | F7`. CMD/FIELD/SUB are 7-bit little-endian u32; `SUB = len<<4 | space`; checksum covers payload + FIELD + SUB bytes. A frame with a bad checksum is silently ignored by the pedal.
- `model.py` — the bank: `A5 5A` + 36 records × 21 bytes (758 bytes), slots `1A..9D` (`slot = (bank-1)*4 + letter`). `FIELDS` maps each byte to a front-panel control; only `amp_type` (byte 5) and `cab` (byte 17) are verified, the rest is inferred from the manual (`verified=False`). Bytes 18–20 are the footswitch LED colour (RGB, inferred). Unknown bytes must round-trip untouched.
- `device.py` — transports + protocol. `find_devices()` prefers ALSA rawmidi on Linux (`/proc/asound/card*/usbid == 4c4a:c755`, `/dev/snd/midiC*D0`, zero deps) and falls back to python-rtmidi (Windows/macOS), matching the port name "USB Composite Device". `TankG.open()` identifies the model by reading the bank (VID:PID is a generic Jieli id shared with other M-VAVE pedals). `write_presets()` writes each changed record (`CLS 09`, `CMD 0x41 + 8*21`, space 0, field `2 + 21*slot`), waits for the ACK, sends COMMIT (space F), then re-reads and verifies. `select_preset()` is MIDI Program Change 0–35 on channel 1.
- `library.py` — files and per-user data: `.tgbank` (raw 758 bytes, same as M-EFCS `tankG_*_preset.bin`), `.tgpreset`/`.tgset` (JSON with hex `raw` + interface names), automatic backups, `Aliases` (preset/bank names: the pedal stores no names, so they live only in `aliases.json`). Data dir: `~/.local/share/tankg` or `%APPDATA%\tankg`.
- `templates.py` — starting-point presets as field dicts.
- `gui.py` / `dialogs.py` — `MainWindow` keeps two banks: `device` (last read from the pedal) and `local` (working copy); "modified" = slots where they differ. Every pedal operation runs in a `Job` (QRunnable) that opens the device, does the work and closes it, so other apps keep MIDI access. Jobs must stay referenced in `self._jobs` until they report back (otherwise their signals are garbage-collected). Edits go through `_set_local()` (undo stack + optional live audition, which writes and re-selects the preset after a debounce).

## Protocol facts and rules

- Verified on hardware: bank read (space 0, len 758), single-record write + commit (persists across power cycle), Program Change select. Spaces 1/2 of the MK-300 protocol do not exist on the Tank-G (they echo a stale buffer).
- Not implemented on purpose (protocol unverified, could overwrite factory data): IR/CAB import, Loopback and other global settings, firmware update.
- `research/FINDINGS.md` is the source of truth for what is verified vs inferred; mark anything new accordingly and never invent commands or byte meanings. The calibration assistant (`dialogs.CalibrationWizard`) exists to confirm the inferred field map.
- Before writing to the pedal, take a backup (`library.backup`); write only changed slots and verify by read-back.
- Three-zone knobs (MOD FX, DLY MIX, RVB DECAY) select one of three effect types by position; zone limits are assumed equal thirds (unverified).
- `tests/live_bank.bin` is a real bank image used as a fixture; golden frames in tests are captures from the real pedal — do not "fix" them to match the code.
- `research/factory/` and `research/TANK-G_en.pdf` are M-VAVE files extracted from M-EFCS; fine in the private repo, remove before making it public.

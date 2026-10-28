"""Build a single-file executable with PyInstaller: dist/TankG (Linux) or dist/TankG.exe (Windows).

usage: python packaging/build.py      (needs: pip install pyinstaller)
"""
import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
SEP = os.pathsep  # PyInstaller --add-data separator

args = [
    str(ROOT / "packaging/launcher.py"),
    "--name", "TankG",
    "--onefile",
    "--noconfirm",
    "--clean",
    "--paths", str(ROOT),
    *[x for name in ("tankG_original_preset.bin", "tankG_original_names.json", "tankG_am4_preset.bin", "tankG_am3_preset.bin",
                     "tankG_am4_ampCab.bin", "tankG_am3_ampCab.bin")
      for x in ("--add-data", f"{ROOT / 'research/factory' / name}{SEP}research/factory")],
    "--add-data", f"{ROOT / 'packaging/icon.png'}{SEP}packaging",
    *[x for f in sorted((ROOT / "packs").glob("*.tgpack")) for x in ("--add-data", f"{f}{SEP}packs")],
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]
if (ROOT / "tankg/cloud_secrets.json").exists():   # Google Drive OAuth clients (gitignored)
    args += ["--add-data", f"{ROOT / 'tankg/cloud_secrets.json'}{SEP}tankg"]
else:
    print("Sin tankg/cloud_secrets.json: el ejecutable no tendrá sincronización con Google Drive")
args += ["--collect-submodules", "bleak"]   # backends are imported by platform at run time
if sys.platform.startswith("linux"):
    # Qt >= 6.5 needs libxcb-cursor for X11 and many systems lack it: ship it next to the app.
    import ctypes.util
    import subprocess
    lib = os.environ.get("XCB_CURSOR_LIB")
    if not lib and ctypes.util.find_library("xcb-cursor"):
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
        lib = next((line.split("=>")[-1].strip() for line in out.splitlines() if "libxcb-cursor.so.0" in line), None)
    if lib:
        args += ["--add-binary", f"{lib}{SEP}."]
    else:
        print("aviso: libxcb-cursor no encontrada; el ejecutable dependerá de la del sistema para X11")
if sys.platform == "win32":
    args += ["--windowed", "--icon", str(ROOT / "packaging/icon.ico"), "--collect-submodules", "winrt"]
else:
    args += ["--collect-submodules", "dbus_fast"]

PyInstaller.__main__.run(args)

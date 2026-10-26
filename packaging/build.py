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
    "--add-data", f"{ROOT / 'research/factory/tankG_am4_preset.bin'}{SEP}research/factory",
    "--add-data", f"{ROOT / 'packaging/icon.png'}{SEP}packaging",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
]
if sys.platform == "win32":
    args += ["--windowed", "--icon", str(ROOT / "packaging/icon.ico")]

PyInstaller.__main__.run(args)

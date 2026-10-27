"""PyInstaller entry script (relative imports in tankg/__main__.py need a package context)."""
import os
import sys

if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    # The bundle points LD_LIBRARY_PATH at its own (older) libraries; system programs started from
    # the app (bluetoothctl, run by bleak to check BlueZ; xdg-open) must use the system ones.
    if "LD_LIBRARY_PATH_ORIG" in os.environ:
        os.environ["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
    else:
        os.environ.pop("LD_LIBRARY_PATH", None)

from tankg.__main__ import run  # noqa: E402

sys.exit(run())

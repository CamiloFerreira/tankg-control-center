"""PyInstaller entry script (relative imports in tankg/__main__.py need a package context)."""
import sys

from tankg.__main__ import run

sys.exit(run())

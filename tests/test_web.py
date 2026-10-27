"""Web/Android app: generated data must be current and the JS protocol must pass its tests
(same golden frames as the Python codec). Skipped when node is not installed."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_web_data_is_current():
    import export_web
    current = export_web.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")   # Windows checkouts may use CRLF
    assert current == export_web.render(), \
        "web/js/data.js desactualizado: ejecuta tools/export_web.py"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_web_protocol():
    r = subprocess.run(["node", str(ROOT / "tests/web/protocol.test.mjs")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr + r.stdout

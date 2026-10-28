"""Isolation for every test: the app's data folder (settings with the Google Drive session, names,
backups) points to a temporary folder before tankg is imported, and the Drive API refuses to go
out unless a test replaces it with a fake. Without this, GUI tests synced test data to the
developer's real Google Drive."""
import os
import tempfile

_DATA = tempfile.mkdtemp(prefix="tankg-tests-")
os.environ["XDG_DATA_HOME"] = _DATA   # Linux/macOS: library.DATA_DIR
os.environ["APPDATA"] = _DATA         # Windows

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_cloud(monkeypatch):
    from tankg import cloud, library
    assert str(library.DATA_DIR).startswith(_DATA), "tests must not use the real data folder"

    def offline(*args, **kwargs):
        raise cloud.CloudError("tests: no network (patch cloud._request with a fake)")

    monkeypatch.setattr(cloud, "_request", offline)

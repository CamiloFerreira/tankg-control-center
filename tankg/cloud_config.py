"""OAuth client of the Google Cloud project used for Drive sync (scope drive.file), created once by
the author with type "TVs and Limited Input devices" (device flow, used on every platform).
It is never committed: tankg/cloud_secrets.json is the JSON downloaded from the Google console
(git-ignored; bundled by packaging/build.py, injected into the APK by android/build.sh, written by
the release workflow from the TANKG_CLOUD_SECRETS secret), or TANKG_GOOGLE_CLIENT_ID/SECRET are set.
Missing values disable the sync. Google does not treat secrets of installed apps as confidential.
"""
import json
import os
import sys
from pathlib import Path


def _load() -> dict:
    for base in (Path(getattr(sys, "_MEIPASS", "")) / "tankg", Path(__file__).resolve().parent):
        try:
            doc = json.loads((base / "cloud_secrets.json").read_text(encoding="utf-8"))
            return doc.get("installed") or doc.get("device") or {}
        except (OSError, ValueError, AttributeError):
            continue
    return {}


_CLIENT = _load()
CLIENT_ID = os.environ.get("TANKG_GOOGLE_CLIENT_ID") or _CLIENT.get("client_id", "")
CLIENT_SECRET = os.environ.get("TANKG_GOOGLE_CLIENT_SECRET") or _CLIENT.get("client_secret", "")

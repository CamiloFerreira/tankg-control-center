"""Open the chat of the AI service in its desktop app when one is installed, else in the browser.

An app is used only when the operating system has a handler registered for its URL scheme
(ai.CHAT_APPS), so nothing happens that the system does not confirm; otherwise the web page opens.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import ai


def scheme_handler(scheme: str) -> bool:
    """True when some installed app handles <scheme>:// links."""
    if not scheme:
        return False
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme) as key:
                winreg.QueryValueEx(key, "URL Protocol")
            return True
        except OSError:
            return False
    if sys.platform.startswith("linux") and shutil.which("xdg-mime"):
        try:
            out = subprocess.run(["xdg-mime", "query", "default", f"x-scheme-handler/{scheme}"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return False
        return bool(out)
    return False


def open_chat(site: str, open_url) -> str:
    """Open `site`'s chat. Returns "app" or "web". open_url(url) opens a web page (Qt in the GUI)."""
    link = ai.CHAT_APPS.get(site, {}).get("desktop", "")
    if link and scheme_handler(link.split(":", 1)[0]):
        try:
            if sys.platform == "win32":
                os.startfile(link)  # noqa: S606 - opens the registered app
            else:
                subprocess.Popen(["xdg-open", link], start_new_session=True)
            return "app"
        except OSError:
            pass
    open_url(ai.WEB_SITES[site])
    return "web"

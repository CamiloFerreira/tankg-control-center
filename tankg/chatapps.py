"""Open the chat of the AI service in its desktop app when one is installed, else in the browser.

An app is used only when the operating system has a handler registered for its URL scheme
(ai.CHAT_APPS), so nothing happens that the system does not confirm; otherwise the web page opens.
Apps that take the prompt in the link (Claude Desktop: ?q=) get it written in the message box.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from urllib.parse import quote

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


def _windows_command(scheme: str, link: str) -> str | None:
    """The registered command line with the link, run directly: ShellExecute limits long URLs."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{scheme}\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
    except OSError:
        return None
    return command.replace("%1", link) if "%1" in command else None


def open_chat(site: str, open_url, text: str = "") -> str:
    """Open `site`'s chat: "shared" (app opened with the prompt written), "app" or "web".
    open_url(url) opens a web page (Qt in the GUI)."""
    app = ai.CHAT_APPS.get(site, {})
    link = app.get("desktop", "")
    scheme = link.split(":", 1)[0] if link else ""
    if link and scheme_handler(scheme):
        shared = bool(text and app.get("prefill") and len(text) <= app.get("limit", 0))
        full = f"{link}?{app['prefill']}={quote(text, safe='')}" if shared else link
        try:
            if sys.platform == "win32":
                command = _windows_command(scheme, full) if shared else None
                if command and len(command) < 32000:
                    subprocess.Popen(command, close_fds=True)
                else:
                    shared = False
                    os.startfile(link)  # noqa: S606 - opens the registered app
            else:
                subprocess.Popen(["xdg-open", full], start_new_session=True)
            return "shared" if shared else "app"
        except OSError:
            pass
    open_url(ai.WEB_SITES[site])
    return "web"

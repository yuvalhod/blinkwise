"""Native desktop notifications without extra dependencies.

Arguments are passed as argv lists (never through a shell), and the text is
escaped for the AppleScript / PowerShell string literals it ends up in.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from typing import List, Optional

log = logging.getLogger(__name__)


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ps_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def build_command(title: str, message: str, platform: Optional[str] = None) -> Optional[List[str]]:
    """The command that shows a notification on this platform, or None if unsupported."""
    platform = platform or sys.platform
    if platform == "darwin":
        script = f"display notification {_applescript_str(message)} with title {_applescript_str(title)}"
        return ["osascript", "-e", script]
    if platform.startswith("linux") or "bsd" in platform:
        if shutil.which("notify-send") is None and platform == sys.platform:
            return None
        return ["notify-send", "--app-name=Blinkwise", "--expire-time=8000", title, message]
    if platform == "win32":
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType=WindowsRuntime] > $null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$x = $t.GetElementsByTagName('text');"
            f"$x.Item(0).AppendChild($t.CreateTextNode({_ps_str(title)})) > $null;"
            f"$x.Item(1).AppendChild($t.CreateTextNode({_ps_str(message)})) > $null;"
            "$n = [Windows.UI.Notifications.ToastNotification]::new($t);"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
            "'Blinkwise').Show($n);"
        )
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]
    return None


def notify(title: str, message: str) -> bool:
    """Show a desktop notification. Returns False if it couldn't (caller may fall back)."""
    cmd = build_command(title, message)
    if cmd is None:
        return False
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        return True
    except OSError as e:
        log.debug("notification failed: %s", e)
        return False

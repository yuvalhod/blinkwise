"""'Start at login' for macOS (LaunchAgent), Windows (Startup folder) and Linux
(XDG autostart). Plain files in the user's own folders; no admin rights."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

LABEL = "com.blinkwise.agent"


def _command() -> List[str]:
    if sys.platform == "darwin":
        # Prefer the installed app bundle: launching through LaunchServices makes macOS
        # attribute camera access to Blinkwise (not to Python) and shows the right icon.
        from ..macos import default_location
        app = default_location()
        if app.exists():
            return ["/usr/bin/open", "-a", str(app)]
    exe = sys.executable
    if sys.platform == "win32":          # no console window at login
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            exe = str(w)
    return [exe, "-m", "blinkwise", "run"]


def path(platform: Optional[str] = None) -> Path:
    platform = platform or sys.platform
    if platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    if platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Blinkwise.cmd"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / "blinkwise.desktop"


def content(platform: Optional[str] = None, cmd: Optional[List[str]] = None) -> str:
    platform = platform or sys.platform
    cmd = cmd or _command()
    if platform == "darwin":
        from xml.sax.saxutils import escape
        args = "\n".join(f"        <string>{escape(a)}</string>" for a in cmd)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
"""
    if platform == "win32":
        quoted = " ".join(f'"{a}"' for a in cmd)
        return f'@echo off\r\nstart "" {quoted}\r\n'
    import shlex
    return ("[Desktop Entry]\nType=Application\nName=Blinkwise\n"
            "Comment=Blink and screen-break coach\n"
            f"Exec={' '.join(shlex.quote(a) for a in cmd)}\n"
            "X-GNOME-Autostart-enabled=true\nNoDisplay=false\n")


def is_enabled(platform: Optional[str] = None) -> bool:
    return path(platform).exists()


def enable(platform: Optional[str] = None) -> Path:
    p = path(platform)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content(platform))
    return p


def disable(platform: Optional[str] = None) -> None:
    p = path(platform)
    if p.exists():
        p.unlink()


def toggle(platform: Optional[str] = None) -> bool:
    if is_enabled(platform):
        disable(platform)
        return False
    enable(platform)
    return True

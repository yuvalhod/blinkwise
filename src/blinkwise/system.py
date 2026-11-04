"""What the computer is doing: on battery? in a video call?

Everything here is best-effort and read-only. It never sends anything anywhere and
returns None when it can't tell, so callers fall back to normal behaviour.

Call detection uses two signals:
  * meeting-only helper processes (Zoom starts ``CptHost`` / ``CptService`` only while
    a meeting is running; FaceTime is a call app by itself);
  * another program holding the webcam (Windows: the privacy "capability access"
    registry; Linux: open handles on /dev/video*). macOS cameras are shared and the OS
    doesn't expose who uses them, so there we rely on process names only.
A call in a browser tab (e.g. Google Meet) on a Mac can't be seen; "Quiet for 1 hour"
in the menu covers that.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

# Lower-cased process names (without .exe) that only exist during a call.
CALL_PROCESSES = {
    "cpthost": "Zoom",
    "cptservice": "Zoom",
    "facetime": "FaceTime",
    "webexmta": "Webex",
    "atmgr": "Webex",
}


def on_battery() -> Optional[bool]:
    """True on battery, False on mains power, None if there is no battery / unknown."""
    try:
        import psutil
        b = psutil.sensors_battery()
    except Exception:
        return None
    if b is None or b.power_plugged is None:
        return None
    return not b.power_plugged


def _process_names() -> Iterable[str]:
    import psutil
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if name.endswith(".exe"):
            name = name[:-4]
        yield name


def call_app_from_processes(names: Iterable[str]) -> Optional[str]:
    for n in names:
        if n in CALL_PROCESSES:
            return CALL_PROCESSES[n]
    return None


def _windows_camera_users() -> list:
    """Apps Windows says are using the webcam right now (LastUsedTimeStop == 0)."""
    import winreg  # type: ignore[import-not-found]
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"
    users = []

    def scan(path):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                if sub == "NonPackaged":
                    scan(path + "\\" + sub)
                    continue
                try:
                    with winreg.OpenKey(key, sub) as k:
                        stop, _ = winreg.QueryValueEx(k, "LastUsedTimeStop")
                        start, _ = winreg.QueryValueEx(k, "LastUsedTimeStart")
                    if stop == 0 and start:
                        users.append(sub)
                except OSError:
                    continue

    scan(base)
    return users


def _linux_camera_users() -> list:
    """PIDs (other than ours) with a /dev/video* device open."""
    me = os.getpid()
    users = []
    try:
        pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return users
    for pid in pids:
        if pid == me:
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            for fd in os.listdir(fd_dir):
                if os.readlink(os.path.join(fd_dir, fd)).startswith("/dev/video"):
                    users.append(pid)
                    break
        except OSError:
            continue                      # other users' processes, or it exited
    return users


def other_app_using_camera(own_markers: Iterable[str] = ()) -> Optional[bool]:
    """True if a different program has the webcam open. None if we can't tell."""
    try:
        if sys.platform == "win32":
            mine = [m.lower() for m in own_markers if m]
            return any(not any(m in u.lower() for m in mine) for u in _windows_camera_users())
        if sys.platform.startswith("linux"):
            return bool(_linux_camera_users())
    except Exception:
        log.debug("camera-use check failed", exc_info=True)
    return None


@dataclass
class SystemState:
    on_battery: Optional[bool] = None
    call: Optional[str] = None            # e.g. "Zoom", "a video call", or None


def probe(*, battery: Callable[[], Optional[bool]] = on_battery,
          processes: Callable[[], Iterable[str]] = _process_names,
          camera_in_use: Optional[Callable[[], Optional[bool]]] = None) -> SystemState:
    s = SystemState(on_battery=battery())
    try:
        s.call = call_app_from_processes(processes())
    except Exception:
        log.debug("process scan failed", exc_info=True)
    if s.call is None:
        check = camera_in_use or (lambda: other_app_using_camera(
            [os.path.basename(sys.executable), "blinkwise"]))
        if check():
            s.call = "a video call"
    return s

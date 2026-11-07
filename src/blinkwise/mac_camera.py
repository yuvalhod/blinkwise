"""macOS camera permission, asked for properly.

OpenCV's AVFoundation backend only *requests* access and fails at once ("not authorized
... requesting"), and for an app that runs Python from a script, macOS may never show the
prompt. Asking through AVFoundation directly shows the real "Blinkwise would like to access
the camera" prompt, and lets us tell "denied" apart from "no face in view".

Every function returns None when it can't tell (not macOS, or PyObjC's AVFoundation
bindings missing); callers then just try to open the camera as before.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from typing import Optional

log = logging.getLogger(__name__)

SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"
_STATUS = {0: "not_determined", 1: "restricted", 2: "denied", 3: "authorized"}


def _av():
    if sys.platform != "darwin":
        return None
    try:
        import AVFoundation
        return AVFoundation
    except Exception:
        log.info("PyObjC AVFoundation not available; can't check camera permission")
        return None


def status() -> Optional[str]:
    """"authorized" | "denied" | "restricted" | "not_determined" | None (unknown)."""
    av = _av()
    if av is None:
        return None
    try:
        return _STATUS.get(int(av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeVideo)))
    except Exception:
        log.debug("camera permission check failed", exc_info=True)
        return None


def request(timeout: float = 120.0) -> Optional[str]:
    """Show macOS's camera prompt (if it hasn't been answered) and wait for the answer."""
    av = _av()
    if av is None:
        return None
    st = status()
    if st != "not_determined":
        return st
    done = threading.Event()

    def handler(granted):
        done.set()
    try:
        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(av.AVMediaTypeVideo, handler)
    except Exception:
        log.debug("camera permission request failed", exc_info=True)
        return None
    done.wait(timeout)
    return status()


def open_settings() -> None:
    try:
        subprocess.run(["open", SETTINGS_URL], check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass

"""Menu-bar (macOS) / system-tray (Windows, Linux) icon and dropdown.

Uses pystray (optional dependency: `pip install "blinkwise[tray]"`).

Threading
  * macOS: the status item must live on the main thread, so the tray owns the
    main thread (`run_blocking`) and every update from other threads is
    marshalled onto it with PyObjCTools.AppHelper.callAfter.
  * Windows/Linux: the tray runs in a background thread (`start_background`),
    leaving the main thread to the Tk overlays.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from . import autostart as autostart_mod
from .icon import BLINK_FRAMES, render
from .menu import Item, build_menu, icon_state

log = logging.getLogger(__name__)
IS_MAC = sys.platform == "darwin"


def available() -> bool:
    """True if a tray backend can be created on this machine (needs a display)."""
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401  (imports connect to the display on Linux)
        return True
    except Exception as e:
        log.info("Tray unavailable: %s", e)
        return False


def mac_dark_mode() -> bool:
    if not IS_MAC:
        return False
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                             capture_output=True, text=True, timeout=2)
        return "Dark" in out.stdout
    except Exception:
        return False


class Tray:
    def __init__(self, get_snapshot: Callable[[], Dict[str, Any]],
                 on_action: Callable[[str], None], get_cue: Callable[[], str],
                 dispatch: Optional[Callable[[Callable[[], None]], None]] = None):
        """`dispatch` runs a callable on the UI thread (the Tk pump); when None, updates
        are applied directly (Windows/Linux) or via AppHelper (macOS without Tk)."""
        import pystray

        self._pystray = pystray
        self.get_snapshot = get_snapshot
        self.on_action = on_action
        self.get_cue = get_cue
        self._size = 44 if IS_MAC else 64
        self._color = (255, 255, 255, 255) if mac_dark_mode() else (0, 0, 0, 255)
        if sys.platform.startswith("linux"):
            self._color = (230, 230, 230, 255)    # most Linux panels are dark
        self._cache: Dict[tuple, Any] = {}
        self._state: tuple = ("open", False)
        self._blinking = False
        self._stop = threading.Event()
        self._dispatch = dispatch
        kwargs = {}
        if IS_MAC and dispatch is not None:
            try:   # attach to the NSApplication Tk already created (Tk runs its event loop)
                from AppKit import NSApplication
                kwargs["darwin_nsapplication"] = NSApplication.sharedApplication()
            except Exception:
                pass
        self.icon = pystray.Icon("blinkwise", self._image(self._state), "Blinkwise",
                                 menu=self._menu(), **kwargs)

    # ------------------------------------------------------------ lifecycle
    def run_blocking(self, setup: Optional[Callable[[], None]] = None) -> None:
        """Own the main thread (macOS)."""
        def _setup(icon):
            icon.visible = True
            self._hide_dock_icon()
            self._make_template()
            threading.Thread(target=self._refresh_loop, name="tray-refresh", daemon=True).start()
            if setup:
                setup()
        self.icon.run(setup=_setup)

    def attach(self) -> None:
        """macOS with Tk: register the status item on Tk's app loop (call before mainloop)."""
        def _setup(icon):
            icon.visible = True
            self._main(self._hide_dock_icon)
            self._main(self._make_template)
        self.icon.run_detached(setup=_setup)
        threading.Thread(target=self._refresh_loop, name="tray-refresh", daemon=True).start()

    def start_background(self) -> None:
        """Run in a worker thread (Windows/Linux)."""
        def _run():
            try:
                self.icon.run(setup=lambda icon: setattr(icon, "visible", True))
            except Exception:
                log.exception("tray stopped")
        threading.Thread(target=_run, name="tray", daemon=True).start()
        threading.Thread(target=self._refresh_loop, name="tray-refresh", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._main(self.icon.stop)

    # --------------------------------------------------------------- updates
    def blink(self) -> None:
        """The stare cue: the eye in the menu bar opens and closes."""
        if self._blinking:
            return
        self._blinking = True

        def run():
            try:
                for _ in range(2):
                    for st in BLINK_FRAMES:
                        self._set_icon((st, False))
                        time.sleep(0.11)
                    time.sleep(0.15)
            finally:
                self._blinking = False
                self._set_icon(self._state)
        threading.Thread(target=run, daemon=True).start()

    def notify(self, title: str, message: str) -> bool:
        try:
            self._main(lambda: self.icon.notify(message, title))
            return True
        except Exception:
            return False

    def _refresh_loop(self) -> None:
        while not self._stop.wait(2.0):
            try:
                snap = self.get_snapshot() or {}
                state = icon_state(snap)
                if state != self._state:
                    self._state = state
                    if not self._blinking:
                        self._set_icon(state)
                self._main(self._update_menu)
            except Exception:
                log.exception("tray refresh failed")

    # -------------------------------------------------------------- internals
    def _image(self, state: tuple):
        if state not in self._cache:
            self._cache[state] = render(state[0], self._size, self._color, badge=state[1])
        return self._cache[state]

    def _set_icon(self, state: tuple) -> None:
        img = self._image(state)

        def apply():
            self.icon.icon = img
            self._make_template()
        self._main(apply)

    def _update_menu(self) -> None:
        self.icon.menu = self._menu()
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _menu(self):
        snap = self.get_snapshot() or {}
        auto = autostart_mod.is_enabled() if sys.platform in ("darwin", "win32", "linux") else None
        items = build_menu(snap, blink_cue=self.get_cue(), autostart=auto)
        return self._pystray.Menu(*[self._to_pystray(i) for i in items])

    def _to_pystray(self, it: Item):
        ps = self._pystray
        if it.separator:
            return ps.Menu.SEPARATOR
        if it.submenu:
            return ps.MenuItem(it.text, ps.Menu(*[self._to_pystray(s) for s in it.submenu]))
        handler = self._handler(it.action)
        kwargs = {"enabled": it.enabled}
        if it.checked is not None:
            checked = it.checked
            kwargs["checked"] = lambda item, c=checked: c
            if it.action and it.action.startswith("cue:"):
                kwargs["radio"] = True
        return ps.MenuItem(it.text, handler, **kwargs)

    def _handler(self, action: Optional[str]):
        # pystray inspects the callback's arity: it must take exactly (icon, item).
        def handler(icon, item):
            if action:
                self._handle(action)
        return handler

    def _handle(self, action: str) -> None:
        if action == "autostart":
            on = autostart_mod.toggle()
            log.info("start at login: %s", on)
        else:
            self.on_action(action)
        self._main(self._update_menu)

    # --- macOS specifics (best effort; harmless elsewhere) --------------------
    def _main(self, fn: Callable[[], None]) -> None:
        if self._dispatch is not None:
            self._dispatch(fn)
            return
        if IS_MAC:
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(fn)
                return
            except Exception:
                pass
        fn()

    def _make_template(self) -> None:
        """Let macOS tint the icon for light/dark menu bars and the selected state."""
        if not IS_MAC:
            return
        try:
            self.icon._status_item.button().image().setTemplate_(True)
        except Exception:
            pass

    @staticmethod
    def _hide_dock_icon() -> None:
        if not IS_MAC:
            return
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().setActivationPolicy_(1)   # accessory: no Dock icon
        except Exception:
            pass


def flatten(items: List[Item], depth: int = 0) -> List[str]:
    """Plain-text rendering of a menu (for logs and tests)."""
    out = []
    for it in items:
        if it.separator:
            out.append("  " * depth + "---")
            continue
        mark = "" if it.checked is None else ("(x) " if it.checked else "( ) ")
        out.append("  " * depth + mark + it.text + (" >" if it.submenu else ""))
        out += flatten(it.submenu, depth + 1)
    return out

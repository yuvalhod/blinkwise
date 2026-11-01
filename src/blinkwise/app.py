"""Wires camera -> tracker -> engine -> UI/dashboard/history together.

Threads:
  main    - Tk UI loop (Tk must own the main thread on macOS), or a plain wait
            loop when running headless.
  worker  - camera capture + vision + engine. The engine is only ever touched
            from this thread; the UI and dashboard send it commands via a queue.
  http    - the local dashboard.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

from .config import Settings, data_dir
from .core.engine import Engine
from .core.events import BreakDue, BreakEnded, StareCue, Suggestion
from .core.storage import History
from .ui import notify as native

log = logging.getLogger(__name__)

IDLE_AFTER_S = 60.0   # no face this long -> low-power polling
IDLE_FPS = 2.0


class App:
    def __init__(self, settings: Settings, *, demo: bool = False, demo_speed: float = 1.0,
                 ui: bool = True, dashboard: bool = True, open_browser: bool = False,
                 history_path: Optional[Path] = None, monitors: Optional[int] = -1):
        self.s = settings
        self.demo = demo
        self.demo_speed = max(0.1, demo_speed)
        self.want_ui = ui
        self.want_dashboard = dashboard
        self.open_browser = open_browser
        self.engine = Engine(settings, monitors=monitors)
        hist = history_path or (data_dir() / ("demo.sqlite" if demo else "history.sqlite"))
        self.history = History(hist) if (settings.store_history or demo) else None
        self.events: "queue.Queue[Any]" = queue.Queue()
        self.commands: "queue.Queue[str]" = queue.Queue()
        self.stop = threading.Event()
        self.paused = threading.Event()
        self._snap_lock = threading.Lock()
        self._snapshot: Dict[str, Any] = {}
        self._wall_offset = 0.0
        self._last_publish = 0.0
        self.server = None
        self.error: Optional[BaseException] = None

    # ----------------------------------------------------------------- public
    def run(self) -> None:
        if self.want_dashboard:
            from .ui.dashboard import DashboardServer
            self.server = DashboardServer(self.s.dashboard_port, self.snapshot, self.history,
                                          self._on_dashboard_action, lambda: self.s)
            url = self.server.start()
            print(f"Dashboard: {url}")
            if self.open_browser:
                webbrowser.open(url)
        worker = threading.Thread(target=self._worker_main, name="vision", daemon=True)
        worker.start()
        try:
            if not (self.want_ui and self._run_tk()):
                self._run_headless()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop.set()
            worker.join(timeout=5)
            if self.server:
                self.server.stop()
            if self.history:
                self.history.close()
        if self.error:
            raise self.error

    def snapshot(self) -> Dict[str, Any]:
        with self._snap_lock:
            return dict(self._snapshot)

    # ----------------------------------------------------------------- worker
    def _worker_main(self) -> None:
        try:
            if self.demo:
                self._loop_demo()
            else:
                self._loop_camera()
        except BaseException as e:  # surface errors to the main thread
            log.exception("vision loop crashed")
            self.error = e
        finally:
            self.stop.set()

    def _loop_demo(self) -> None:
        from .core.simulate import Simulation, demo_scenario
        sim = Simulation(demo_scenario())
        start = time.monotonic()
        self._wall_offset = time.time()
        for f in sim.frames():
            if self.stop.is_set():
                return
            while self.paused.is_set() and not self.stop.is_set():
                self._drain_commands()
                self._publish()
                time.sleep(0.1)
            delay = start + f.t / self.demo_speed - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._step(f)

    def _loop_camera(self) -> None:
        from .vision.camera import FrameSource
        from .vision.tracker import FaceTracker, ensure_model
        model = ensure_model(data_dir())
        tracker = FaceTracker(model, self.s.camera_hfov_deg, self.s.focal_px)
        self._wall_offset = time.time() - time.monotonic()
        src = None
        last_face = time.monotonic()
        try:
            while not self.stop.is_set():
                if self.paused.is_set():
                    if src is not None:
                        src.release()          # camera light goes off while paused
                        src = None
                    self._drain_commands()
                    self._publish()
                    time.sleep(0.2)
                    continue
                if src is None:
                    src = FrameSource(self.s.camera, max_fps=self.s.max_fps)
                item = src.read()
                if item is None:
                    time.sleep(0.05)
                    continue
                t, frame = item
                f = tracker.process(frame, t)
                if f.face:
                    last_face = t
                self._step(f)
                if t - last_face > IDLE_AFTER_S:
                    time.sleep(1.0 / IDLE_FPS)   # nobody there: save CPU/battery
        finally:
            if src is not None:
                src.release()
            tracker.close()

    def _step(self, f) -> None:
        self._drain_commands()
        for ev in self.engine.step(f):
            self._emit(ev)
        now = time.monotonic()
        if now - self._last_publish >= 0.2:      # the dashboard polls at 1 Hz
            self._last_publish = now
            self._publish()

    def _emit(self, ev: Any) -> None:
        if self.history is not None:
            self.history.record(ev, self._wall_offset + getattr(ev, "t", f_t(self.engine)))
        self.events.put(ev)

    def _publish(self) -> None:
        snap = self.engine.snapshot()
        snap.update(paused=self.paused.is_set(), demo=self.demo, stare_seconds=self.s.stare_seconds)
        with self._snap_lock:
            self._snapshot = snap

    def _drain_commands(self) -> None:
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                return
            if cmd in ("timer", "skipped"):
                ev = self.engine.end_break(cmd)
                if ev is not None:
                    self._emit(ev)
            elif cmd == "break_now":
                b = self.engine.breaks
                if b.active is None:
                    b.since_micro = b.micro_interval(False)  # due on the next tick
                    b.snoozed_until = -1e9

    def _on_dashboard_action(self, action: str) -> Dict[str, Any]:
        if action == "pause":
            self.paused.set()
        elif action == "resume":
            self.paused.clear()
        elif action == "break_now":
            self.commands.put("break_now")
        elif action == "skip_break":
            self.events.put(("close_break", None))
            self.commands.put("skipped")
        return {"ok": True, "paused": self.paused.is_set()}

    # --------------------------------------------------------------------- UI
    def _run_tk(self) -> bool:
        from .ui import overlay
        if not overlay.TK_AVAILABLE:
            log.info("Tkinter not available; using system notifications only.")
            return False
        try:
            root = overlay.tk.Tk()
        except Exception as e:  # e.g. no display
            log.info("No GUI available (%s); using system notifications only.", e)
            return False
        root.withdraw()
        root.title("Blinkwise")
        cue = overlay.BlinkCue(root)
        card = overlay.BreakCard(root, on_done=self.commands.put)
        toast = overlay.Toast(root, self.server.url if self.server else None)

        def pump():
            if self.stop.is_set():
                root.quit()
                return
            while True:
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    break
                self._handle_ui_event(ev, cue, card, toast)
            root.after(50, pump)

        root.after(50, pump)
        print("Blinkwise is running. Press Ctrl+C here to quit.")
        try:
            root.mainloop()
        finally:
            try:
                root.destroy()
            except Exception:
                pass
        return True

    def _handle_ui_event(self, ev, cue, card, toast) -> None:
        if isinstance(ev, tuple) and ev[0] == "close_break":
            card.finish("skipped", notify_engine=False)
        elif isinstance(ev, StareCue):
            if self.s.blink_cue == "subtle":
                cue.show()
            elif self.s.blink_cue == "notify":
                native.notify("Blink", f"No blink for {ev.seconds_since_blink:.0f} s.")
        elif isinstance(ev, BreakDue):
            if self.s.break_style == "notify":
                native.notify("Eye break", ev.exercise or ev.reason)
            else:
                card.show(ev.kind, ev.seconds, ev.reason, ev.exercise)
        elif isinstance(ev, BreakEnded):
            if ev.outcome in ("rested", "missed"):     # engine decided; close the card quietly
                card.finish(ev.outcome, notify_engine=False)
        elif isinstance(ev, Suggestion) and ev.notify:
            toast.show(ev.title, ev.message)

    def _run_headless(self) -> None:
        print("Blinkwise is running (no on-screen overlay). Press Ctrl+C to quit.")
        while not self.stop.is_set():
            try:
                ev = self.events.get(timeout=0.5)
            except queue.Empty:
                continue
            if isinstance(ev, StareCue) and self.s.blink_cue != "off":
                if self.s.blink_cue == "notify":
                    native.notify("Blink", f"No blink for {ev.seconds_since_blink:.0f} s.")
            elif isinstance(ev, BreakDue):
                print(f"[break] {ev.kind}: {ev.exercise}")
                native.notify("Eye break", ev.exercise or ev.reason)
            elif isinstance(ev, BreakEnded):
                print(f"[break] {ev.kind} -> {ev.outcome}")
            elif isinstance(ev, Suggestion):
                print(f"[{ev.severity}] {ev.title}: {ev.message}")
                if ev.notify:
                    native.notify(ev.title, ev.message)


def f_t(engine: Engine) -> float:
    return engine._last_t or 0.0

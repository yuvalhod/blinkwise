"""On-screen cues with Tkinter (ships with Python on Windows and macOS).

* BlinkCue  - a small eye at the top of the screen that blinks twice and
              fades. Based on the "blink blink" animation studied by Nosch et
              al. (2015), where users were asked to blink along with it.
* BreakCard - a calm card with a countdown for 20-20-20 and longer breaks;
              it can always be skipped. Nothing ever locks the screen.
* Toast     - an in-app notification for coaching suggestions.

Tk must run on the main thread (required on macOS), so the camera loop runs
in a worker thread and talks to this module through a queue.
"""

from __future__ import annotations

import math
import webbrowser
from typing import Callable, Optional

try:
    import tkinter as tk
    TK_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the Python build
    tk = None  # type: ignore
    TK_AVAILABLE = False

BG = "#14181f"
FG = "#e9eef5"
MUTED = "#9aa7b8"
ACCENT = "#5cc8a8"
FONT = ("Helvetica", 12)


def _topmost(win) -> None:
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    try:
        win.attributes("-alpha", 0.0)
    except tk.TclError:
        pass


def _fade(win, target: float, step: float = 0.08, done: Optional[Callable] = None) -> None:
    try:
        cur = float(win.attributes("-alpha"))
    except Exception:
        if done:
            done()
        return
    if abs(cur - target) <= step:
        try:
            win.attributes("-alpha", target)
        except Exception:
            pass
        if done:
            done()
        return
    win.attributes("-alpha", cur + (step if target > cur else -step))
    win.after(16, lambda: _fade(win, target, step, done))


class BlinkCue:
    W, H = 120, 56

    def __init__(self, root):
        self.root = root
        self.win: Optional[tk.Toplevel] = None
        self._busy = False

    def show(self) -> None:
        if self._busy:
            return
        self._busy = True
        win = self.win = tk.Toplevel(self.root)
        _topmost(win)
        sw = win.winfo_screenwidth()
        win.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{12}")
        c = tk.Canvas(win, width=self.W, height=self.H, bg=BG, highlightthickness=0)
        c.pack()
        self._canvas = c
        self._frame = 0
        _fade(win, 0.88, done=self._animate)

    def _draw(self, openness: float) -> None:
        c, cx, cy = self._canvas, self.W / 2, self.H / 2
        c.delete("all")
        rx, ry = 34, 16 * max(openness, 0.05)
        pts = []
        for i in range(41):
            a = math.pi * i / 40
            pts += [cx - rx * math.cos(a), cy - ry * math.sin(a)]
        for i in range(41):
            a = math.pi * i / 40
            pts += [cx + rx * math.cos(a), cy + ry * math.sin(a)]
        c.create_polygon(pts, fill="#2a3340", outline=ACCENT, width=2, smooth=True)
        if openness > 0.35:
            r = 7 * min(1.0, openness)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=ACCENT, outline="")

    def _animate(self) -> None:
        # Two blinks: open -> closed -> open, twice, ~0.35 s each, then hold and fade.
        f = self._frame
        self._frame += 1
        period = 22
        if f < 2 * period:
            phase = (f % period) / period
            self._draw(0.5 + 0.5 * math.cos(2 * math.pi * phase))
            self.win.after(16, self._animate)
        elif f < 2 * period + 30:
            self._draw(1.0)
            self.win.after(16, self._animate)
        else:
            _fade(self.win, 0.0, done=self._close)

    def _close(self) -> None:
        if self.win is not None:
            self.win.destroy()
        self.win = None
        self._busy = False


class BreakCard:
    W, H = 460, 230

    def __init__(self, root, on_done: Callable[[str], None]):
        self.root = root
        self.on_done = on_done
        self.win: Optional[tk.Toplevel] = None

    @property
    def active(self) -> bool:
        return self.win is not None

    def show(self, kind: str, seconds: float, reason: str, exercise: Optional[str]) -> None:
        if self.win is not None:
            return
        win = self.win = tk.Toplevel(self.root)
        _topmost(win)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 3}")
        frame = tk.Frame(win, bg=BG, padx=24, pady=18)
        frame.pack(fill="both", expand=True)
        title = "Eye break - 20-20-20" if kind == "micro" else "Time for a real break"
        tk.Label(frame, text=title, bg=BG, fg=FG, font=("Helvetica", 17, "bold")).pack(anchor="w")
        tk.Label(frame, text=exercise or "", bg=BG, fg=FG, font=FONT, wraplength=self.W - 48,
                 justify="left").pack(anchor="w", pady=(8, 2))
        tk.Label(frame, text=reason, bg=BG, fg=MUTED, font=("Helvetica", 10),
                 wraplength=self.W - 48, justify="left").pack(anchor="w")
        self._bar = tk.Canvas(frame, height=6, bg="#2a3340", highlightthickness=0)
        self._bar.pack(fill="x", pady=(14, 10))
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        self._count = tk.Label(row, text="", bg=BG, fg=ACCENT, font=("Helvetica", 14, "bold"))
        self._count.pack(side="left")
        tk.Button(row, text="Skip", command=lambda: self.finish("skipped"),
                  relief="flat", bg="#2a3340", fg=FG, activebackground="#36404f",
                  activeforeground=FG, padx=14).pack(side="right")
        self._total = max(1.0, seconds)
        self._left = seconds
        _fade(win, 0.96)
        self._tick()

    def _tick(self) -> None:
        if self.win is None:
            return
        frac = 1 - self._left / self._total
        w = max(1, self._bar.winfo_width())
        self._bar.delete("all")
        self._bar.create_rectangle(0, 0, w * frac, 6, fill=ACCENT, outline="")
        m, s = divmod(int(math.ceil(self._left)), 60)
        self._count.config(text=f"{m}:{s:02d}" if m else f"{s} s")
        if self._left <= 0:
            self.finish("timer")
            return
        self._left -= 0.25
        self.win.after(250, self._tick)

    def finish(self, outcome: str, notify_engine: bool = True) -> None:
        if self.win is None:
            return
        win, self.win = self.win, None
        _fade(win, 0.0, done=win.destroy)
        if notify_engine:
            self.on_done(outcome)


class Toast:
    W, H = 380, 130

    def __init__(self, root, dashboard_url: Optional[str]):
        self.root = root
        self.url = dashboard_url
        self.win: Optional[tk.Toplevel] = None

    def show(self, title: str, message: str, seconds: float = 12.0) -> None:
        if self.win is not None:
            self.win.destroy()
        win = self.win = tk.Toplevel(self.root)
        _topmost(win)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{self.W}x{self.H}+{sw - self.W - 24}+{sh - self.H - 72}")
        f = tk.Frame(win, bg=BG, padx=16, pady=12, highlightthickness=1,
                     highlightbackground="#2a3340")
        f.pack(fill="both", expand=True)
        tk.Label(f, text=title, bg=BG, fg=FG, font=("Helvetica", 13, "bold"),
                 wraplength=self.W - 32, justify="left").pack(anchor="w")
        short = message if len(message) < 150 else message[:147].rsplit(" ", 1)[0] + "..."
        tk.Label(f, text=short, bg=BG, fg=MUTED, font=("Helvetica", 10),
                 wraplength=self.W - 32, justify="left").pack(anchor="w", pady=(4, 0))
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", side="bottom")
        if self.url:
            link = tk.Label(row, text="Why? See the details", bg=BG, fg=ACCENT, cursor="hand2",
                            font=("Helvetica", 10, "underline"))
            link.pack(side="left")
            link.bind("<Button-1>", lambda _e: webbrowser.open(self.url))
        close = tk.Label(row, text="Dismiss", bg=BG, fg=MUTED, cursor="hand2", font=("Helvetica", 10))
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self._close(win))
        _fade(win, 0.95)
        win.after(int(seconds * 1000), lambda: self._close(win))

    def _close(self, win) -> None:
        if self.win is win:
            self.win = None
        try:
            _fade(win, 0.0, done=win.destroy)
        except Exception:
            pass

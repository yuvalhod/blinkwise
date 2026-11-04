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

BG = "#1e1b17"            # warm charcoal, the dashboard's dark "paper"
FG = "#f0e9dd"
MUTED = "#aaa092"
ACCENT = "#ff8250"        # vermilion
RULE = "#3a342b"
SERIF = "Georgia"         # Fraunces can't be loaded into Tk; Georgia ships everywhere
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


def draw_eye(c, cx: float, cy: float, w: float, openness: float, color: str,
             lashes: bool = True, width: float = 3.0) -> None:
    """Draw the Blinkwise eye on a Tk canvas: open -> closed with lashes (matches the icon).

    openness 1 = open (almond + pupil, lashes up), 0 = closed (a downward lid curve with
    lashes hanging below).
    """
    o = max(0.0, min(1.0, openness))
    rx, h, sag = w / 2, w * 0.24, w * 0.20
    n = 24
    up = [(cx - rx + 2 * rx * i / n,
           cy + (sag * (1 - o) - h * o) * math.sin(math.pi * i / n)) for i in range(n + 1)]
    lo = [(cx - rx + 2 * rx * i / n,
           cy + (sag * (1 - o) + h * o) * math.sin(math.pi * i / n)) for i in range(n + 1)]
    if o > 0.05:
        pts = [v for p in up + lo[::-1] for v in p]
        c.create_polygon(pts, fill="", outline=color, width=width, smooth=True)
        if o > 0.55:
            r = h * 0.7 * min(1.0, (o - 0.4) / 0.6)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
    else:
        c.create_line([v for p in up for v in p], fill=color, width=width, smooth=True,
                      capstyle="round")
    if lashes:
        k = 5
        sign = -1 if o > 0.5 else 1
        lid = up if o > 0.5 else lo
        for i in range(k):
            f = (i + 1) / (k + 1)
            x, y = lid[round(f * n)]
            spread = (f - 0.5) * 1.2
            ln = w * 0.15
            c.create_line(x, y, x + math.sin(spread) * ln, y + sign * math.cos(spread) * ln,
                          fill=color, width=max(1.5, width * 0.8), capstyle="round")


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
        self._canvas.delete("all")
        draw_eye(self._canvas, self.W / 2, self.H / 2 + 2, 70, openness, ACCENT, width=2.5)

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
        tk.Label(frame, text=title, bg=BG, fg=FG, font=(SERIF, 19)).pack(anchor="w")
        tk.Label(frame, text=exercise or "", bg=BG, fg=FG, font=FONT, wraplength=self.W - 48,
                 justify="left").pack(anchor="w", pady=(8, 2))
        tk.Label(frame, text=reason, bg=BG, fg=MUTED, font=("Helvetica", 10),
                 wraplength=self.W - 48, justify="left").pack(anchor="w")
        self._bar = tk.Canvas(frame, height=6, bg=RULE, highlightthickness=0)
        self._bar.pack(fill="x", pady=(14, 10))
        row = tk.Frame(frame, bg=BG)
        row.pack(fill="x")
        self._count = tk.Label(row, text="", bg=BG, fg=ACCENT, font=("Helvetica", 14, "bold"))
        self._count.pack(side="left")
        tk.Button(row, text="Skip", command=lambda: self.finish("skipped"),
                  relief="flat", bg=RULE, fg=FG, activebackground="#4a4238",
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
                     highlightbackground=RULE)
        f.pack(fill="both", expand=True)
        tk.Label(f, text=title, bg=BG, fg=FG, font=(SERIF, 15),
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


class BigBlink:
    """The 'Coach' stare cue: a large centred eye that blinks twice with the word Blink."""

    W, H = 340, 240

    def __init__(self, root):
        self.root = root
        self.win = None

    def show(self) -> None:
        if self.win is not None:
            return
        win = self.win = tk.Toplevel(self.root)
        _topmost(win)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{(sh - self.H) // 2 - 40}")
        self.c = tk.Canvas(win, width=self.W, height=self.H, bg=BG, highlightthickness=0)
        self.c.pack()
        self.frame = 0
        _fade(win, 0.93, step=0.12, done=self._animate)

    def _animate(self) -> None:
        if self.win is None:
            return
        f = self.frame
        self.frame += 1
        period = 26
        if f < 2 * period:
            o = 0.5 + 0.5 * math.cos(2 * math.pi * (f % period) / period)
        else:
            o = 1.0
        self.c.delete("all")
        draw_eye(self.c, self.W / 2, self.H / 2 - 22, 190, o, ACCENT, width=6)
        self.c.create_text(self.W / 2, self.H - 46, text="Blink", fill=FG,
                           font=(SERIF, 32))
        self.c.create_text(self.W / 2, self.H - 16, text="slowly, all the way closed", fill=MUTED,
                           font=("Helvetica", 12))
        if f < 2 * period + 35:
            self.win.after(16, self._animate)
        else:
            win, self.win = self.win, None
            _fade(win, 0.0, step=0.08, done=win.destroy)


class ImmersiveBreak:
    """The 'Coach' break: dims the whole screen with a big countdown.

    Skip appears after `skip_delay` seconds (and Esc always works after that), so it's
    firm without ever trapping anyone.
    """

    def __init__(self, root, on_done: Callable[[str], None]):
        self.root = root
        self.on_done = on_done
        self.win = None

    @property
    def active(self) -> bool:
        return self.win is not None

    def show(self, kind: str, seconds: float, exercise: Optional[str], skip_delay: float = 5.0) -> None:
        if self.win is not None:
            return
        win = self.win = tk.Toplevel(self.root)
        _topmost(win)
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"{sw}x{sh}+0+0")
        win.configure(bg="#161411")
        self.W, self.H = sw, sh
        self.c = tk.Canvas(win, width=sw, height=sh, bg="#161411", highlightthickness=0)
        self.c.pack(fill="both", expand=True)
        self.kind = kind
        self.total = max(1.0, seconds)
        self.left = seconds
        self.skip_at = max(0.0, skip_delay)
        self.elapsed = 0.0
        self.title = ("Look at something far away" if kind == "micro"
                      else "Time for a real break")
        self.sub = exercise or ""
        self.btn = tk.Button(win, text="Skip", command=lambda: self.finish("skipped"),
                             relief="flat", bg="#2a2620", fg=FG, activebackground="#3a342b",
                             activeforeground=FG, padx=18, pady=6, font=("Helvetica", 13))
        win.bind("<Escape>", lambda _e: self._esc())
        win.focus_force()
        _fade(win, 0.94, step=0.06)
        self._tick()

    def _esc(self) -> None:
        if self.elapsed >= self.skip_at:
            self.finish("skipped")

    def _tick(self) -> None:
        if self.win is None:
            return
        c, W, H = self.c, self.W, self.H
        c.delete("all")
        breathe = 0.5 + 0.5 * math.cos(2 * math.pi * self.elapsed / 6.0)   # slow 6 s blink
        draw_eye(c, W / 2, H * 0.30, min(260, W * 0.22), breathe, ACCENT, width=7)
        c.create_text(W / 2, H * 0.47, text=self.title, fill=FG, font=(SERIF, 38))
        c.create_text(W / 2, H * 0.53, text=self.sub, fill=MUTED, font=("Helvetica", 16),
                      width=min(760, W * 0.8), justify="center")
        left = max(0, math.ceil(self.left))
        m, s = divmod(left, 60)
        c.create_text(W / 2, H * 0.68, text=f"{m}:{s:02d}" if m else str(s), fill=FG,
                      font=(SERIF, 110))
        bw = min(520, W * 0.5)
        frac = 1 - self.left / self.total
        c.create_rectangle(W / 2 - bw / 2, H * 0.78, W / 2 + bw / 2, H * 0.78 + 8,
                           fill="#2a2620", outline="")
        c.create_rectangle(W / 2 - bw / 2, H * 0.78, W / 2 - bw / 2 + bw * frac, H * 0.78 + 8,
                           fill=ACCENT, outline="")
        if self.elapsed >= self.skip_at:
            c.create_window(W / 2, H * 0.86, window=self.btn)
        else:
            c.create_text(W / 2, H * 0.86, fill=MUTED, font=("Helvetica", 12),
                          text=f"Skip available in {math.ceil(self.skip_at - self.elapsed)} s")
        if self.left <= 0:
            self._celebrate()
            return
        self.left -= 0.1
        self.elapsed += 0.1
        self.win.after(100, self._tick)

    def _celebrate(self) -> None:
        c, W, H = self.c, self.W, self.H
        c.delete("all")
        draw_eye(c, W / 2, H * 0.40, min(260, W * 0.22), 1.0, ACCENT, width=7)
        c.create_text(W / 2, H * 0.58, text="Nice. Back to it.", fill=FG,
                      font=(SERIF, 38))
        self.win.after(1200, lambda: self.finish("timer"))

    def finish(self, outcome: str, notify_engine: bool = True) -> None:
        if self.win is None:
            return
        win, self.win = self.win, None
        _fade(win, 0.0, step=0.1, done=win.destroy)
        if notify_engine:
            self.on_done(outcome)

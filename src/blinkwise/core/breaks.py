"""Break scheduling that notices when you've already rested.

* Micro break (20-20-20): every ~20 min of screen time, look ~6 m / 20 ft away
  for 20 s. Talens-Estarelles et al. (2023) found webcam-driven reminders of
  this kind reduced digital eye strain symptoms.
* Long break: ~5 min every hour of screen time (Galinsky et al. 2000 NIOSH study).

Only *screen time* counts toward the next break: if the camera sees you look
away or leave for long enough, that already counts as the break, and the
reminder is skipped. When your blink rate is low, breaks come sooner
(adaptive mode).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .events import BreakDue, BreakEnded

MICRO_EXERCISE = ("Look at something at least 6 m (20 ft) away - out of a window if you can - "
                  "and blink slowly a few times.")
LONG_EXERCISE = ("Stand up and move. Neck: roll your shoulders back 5 times and gently tuck "
                 "your chin 5 times. Eyes: close gently (2 s), squeeze gently (2 s), open - "
                 "repeat 10 times.")


@dataclass
class _Active:
    kind: str
    due_at: float
    seconds: float
    rested: float = 0.0


class BreakScheduler:
    def __init__(self, micro_minutes: float = 20, micro_seconds: float = 20,
                 long_minutes: float = 60, long_seconds: float = 300,
                 adaptive: bool = True, grace_s: float = 120.0, snooze_s: float = 300.0):
        self.micro_s = micro_minutes * 60
        self.micro_len = micro_seconds
        self.long_s = long_minutes * 60
        self.long_len = long_seconds
        self.adaptive = adaptive
        self.grace_s = grace_s
        self.snooze_s = snooze_s
        self.since_micro = 0.0          # screen seconds since last micro break
        self.since_long = 0.0
        self.away_run = 0.0             # current continuous resting/away time
        self.snoozed_until = -1e9
        self._t = 0.0
        self.active: Optional[_Active] = None
        self.completed = {"micro": 0, "long": 0}
        self.missed = {"micro": 0, "long": 0}

    def micro_interval(self, low_blink: bool) -> float:
        return self.micro_s * (0.75 if self.adaptive and low_blink else 1.0)

    def seconds_to_next(self, low_blink: bool = False) -> float:
        due = min(self.micro_interval(low_blink) - self.since_micro, self.long_s - self.since_long)
        return max(0.0, due, self.snoozed_until - self._t)

    def tick(self, t: float, dt: float, on_screen: bool, low_blink: bool = False) -> List[object]:
        """on_screen=False means the user is away, looking well away, or resting their eyes."""
        out: List[object] = []
        self._t = t
        if on_screen:
            self.away_run = 0.0
            self.since_micro += dt
            self.since_long += dt
        else:
            self.away_run += dt
            if self.away_run >= self.micro_len:
                self.since_micro = 0.0
            if self.away_run >= self.long_len:
                self.since_long = 0.0

        if self.active is not None:
            a = self.active
            a.rested = a.rested + dt if not on_screen else a.rested
            if a.rested >= a.seconds * 0.75:
                out.append(self._finish("rested"))
            elif t - a.due_at > max(self.grace_s, 3 * a.seconds):
                out.append(self._finish("missed"))
            return out

        if t < self.snoozed_until:
            return out
        if self.since_long >= self.long_s:
            self.active = _Active("long", t, self.long_len)
            out.append(BreakDue("long", self.long_len,
                                f"{self.since_long / 60:.0f} minutes of screen time since your "
                                "last real break", LONG_EXERCISE))
        elif self.since_micro >= self.micro_interval(low_blink):
            self.active = _Active("micro", t, self.micro_len)
            reason = f"{self.since_micro / 60:.0f} minutes of screen time"
            if low_blink and self.adaptive:
                reason += " (brought forward because you're blinking less than usual)"
            out.append(BreakDue("micro", self.micro_len, reason, MICRO_EXERCISE))
        return out

    def finish(self, outcome: str) -> Optional[BreakEnded]:
        """Called by the UI: 'timer' (overlay ran its course) or 'skipped'."""
        if self.active is None:
            return None
        return self._finish(outcome)

    def _finish(self, outcome: str) -> BreakEnded:
        a = self.active
        assert a is not None
        self.active = None
        if outcome in ("rested", "timer"):
            self.completed[a.kind] += 1
            self.since_micro = 0.0
            if a.kind == "long":
                self.since_long = 0.0
        else:
            self.missed[a.kind] += 1
            # Ask again later rather than nagging immediately.
            self.snoozed_until = self._t + self.snooze_s
        return BreakEnded(a.kind, outcome)

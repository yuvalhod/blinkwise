"""How pushy should Blinkwise be? Measured, not guessed.

The camera can tell whether a reminder *worked*: after a stare cue, did you
blink within a few seconds? That gives a response rate per person, which drives
"adaptive" coaching:

  * keep ignoring the gentle cue (menu-bar blink)  -> step up (small on-screen eye,
    then a big centred "Blink" prompt)
  * respond reliably                               -> step back down

Rationale: reminder fatigue is real (people tune out repetitive prompts), but in
Talens-Estarelles et al. (2023) the benefit of break reminders faded within a
week of stopping them, so the goal is the *least* intrusive cue that still works
for this person.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional

LADDER = ("menubar", "subtle", "big")       # least -> most intrusive stare cues


@dataclass
class CueResponse:
    window_s: float = 4.0                   # a blink this soon after a cue counts as a response
    history: int = 12
    _pending: List[float] = field(default_factory=list)
    _results: Deque[bool] = field(default_factory=deque)

    def cue(self, t: float) -> None:
        self._pending.append(t)

    def blink(self, t: float) -> None:
        for c in [c for c in self._pending if 0 <= t - c <= self.window_s]:
            self._pending.remove(c)
            self._add(True)

    def tick(self, t: float) -> None:
        for c in [c for c in self._pending if t - c > self.window_s]:
            self._pending.remove(c)
            self._add(False)

    def _add(self, ok: bool) -> None:
        self._results.append(ok)
        while len(self._results) > self.history:
            self._results.popleft()

    def reset(self) -> None:
        self._results.clear()

    @property
    def count(self) -> int:
        return len(self._results)

    def rate(self, min_count: int = 5) -> Optional[float]:
        if len(self._results) < min_count:
            return None
        return sum(self._results) / len(self._results)


class Escalator:
    """Moves along LADDER based on how reliably cues get a blink in response."""

    def __init__(self, start: str = "subtle", low: float = 0.3, high: float = 0.75,
                 min_level: str = "menubar", max_level: str = "big"):
        self.level = LADDER.index(start) if start in LADDER else 1
        self.low, self.high = low, high
        self.min_i, self.max_i = LADDER.index(min_level), LADDER.index(max_level)
        self.responses = CueResponse()

    @property
    def cue(self) -> str:
        return LADDER[self.level]

    def on_cue(self, t: float) -> None:
        self.responses.cue(t)

    def on_blink(self, t: float) -> None:
        self.responses.blink(t)

    def tick(self, t: float) -> Optional[str]:
        """Returns 'up' / 'down' when the level changes."""
        self.responses.tick(t)
        r = self.responses.rate(min_count=6)
        if r is None:
            return None
        if r < self.low and self.level < self.max_i:
            self.level += 1
            self.responses.reset()
            return "up"
        if r > self.high and self.level > self.min_i:
            self.level -= 1
            self.responses.reset()
            return "down"
        return None

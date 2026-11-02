"""Rolling blink statistics over *observed* time.

Rates are computed per minute of time the user's eyes were actually visible,
so stepping away from the desk doesn't make your blink rate look low.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from ..vision.blink import Blink


@dataclass
class _Bucket:
    observed: float = 0.0
    blinks: int = 0
    judged: int = 0          # blinks whose completeness could be judged (fps >= 20)
    incomplete: int = 0
    long: int = 0
    closed: float = 0.0      # seconds with eyes >= 80% closed (PERCLOS numerator)


@dataclass
class WindowStats:
    window_s: float
    observed_s: float
    blinks: int
    rate: Optional[float]              # blinks/min, None if not enough observed time
    incomplete_ratio: Optional[float]  # None if too few judged blinks
    long_per_min: Optional[float]
    perclos: Optional[float] = None    # fraction of observed time with eyes >= 80% closed


class RollingStats:
    def __init__(self, horizon_s: float = 3600.0):
        self.horizon_s = horizon_s
        self._b: "OrderedDict[int, _Bucket]" = OrderedDict()

    def _bucket(self, t: float) -> _Bucket:
        k = int(t)
        b = self._b.get(k)
        if b is None:
            b = self._b[k] = _Bucket()
            while self._b and k - next(iter(self._b)) > self.horizon_s:
                self._b.popitem(last=False)
        return b

    def add_observed(self, t: float, dt: float) -> None:
        self._bucket(t).observed += dt

    def add_blink(self, b: Blink) -> None:
        bk = self._bucket(b.t)
        bk.blinks += 1
        if b.complete is not None:
            bk.judged += 1
            bk.incomplete += int(not b.complete)
        bk.long += int(b.long)

    def window(self, now: float, window_s: float, min_observed_s: float = 30.0,
               min_judged: int = 10) -> WindowStats:
        lo = int(now - window_s)
        obs = blinks = judged = inc = lng = closed = 0
        for k in reversed(self._b):
            if k < lo:
                break
            b = self._b[k]
            obs += b.observed
            blinks += b.blinks
            judged += b.judged
            inc += b.incomplete
            lng += b.long
            closed += b.closed
        enough = obs >= min_observed_s
        return WindowStats(
            window_s=window_s, observed_s=obs, blinks=blinks,
            rate=(blinks / obs * 60.0) if enough else None,
            incomplete_ratio=(inc / judged) if judged >= min_judged else None,
            long_per_min=(lng / obs * 60.0) if enough else None,
            perclos=(min(1.0, closed / obs)) if enough else None,
        )

    def add_closed(self, t: float, seconds: float) -> None:
        self._bucket(t).closed += seconds

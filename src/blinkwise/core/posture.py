"""Posture from the same head pose and distance the eye tracking already measures.

Three patterns a webcam can see reliably, each judged against *your own* baseline
(people sit differently and cameras sit at different heights, so absolute angles
would be wrong for many users):

  leaning in   your eyes are >= 15% closer to the screen than when you sit back
               (baseline: the 80th percentile of distance over the last hour)
  chin down    head pitched >= 12 degrees below how you usually hold it when looking
               in the same direction (so a laptop below a monitor isn't "slouching";
               looking at a phone is tracked separately); a slumped, forward-head
               position. Baseline: 70th percentile of pitch over the last hour within
               10 degrees of your current yaw
  head tilt    head rolled >= 12 degrees to one side

A pattern counts once it has lasted 20 s (glances and stretches don't), and a nudge
needs 3 minutes. We don't claim to see your back: "slouching" is inferred from
head position, the part that strains the neck and changes your viewing distance.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

LEAN_RATIO = 0.85
CHIN_DOWN_DEG = 12.0
TILT_DEG = 12.0
SUSTAIN_S = 20.0           # a pattern must last this long to count
NUDGE_AFTER_S = 180.0      # ...and this long before we suggest a change
BASELINE_S = 3600.0
MIN_BASELINE_S = 300.0     # need 5 minutes of data before judging
SAMPLE_EVERY_S = 1.0
SHORT_S = 20.0             # current posture = median over the last 20 s

LABELS = {"leaning_in": "Leaning in", "chin_down": "Chin down", "head_tilt": "Head tilted"}


@dataclass
class PostureTracker:
    _samples: Deque[Tuple[float, Optional[float], float, float, float]] = field(default_factory=deque)
    _last_sample: float = -1e9
    _span_s: float = 0.0
    _since: Dict[str, float] = field(default_factory=dict)   # pattern -> start time
    current: Optional[str] = None                              # the active pattern, if any
    _base_dist: Tuple[float, Optional[float]] = (-1e9, None)

    def update(self, t: float, dt: float, on_screen: bool, pitch: float, roll: float,
               distance_cm: Optional[float], yaw: float = 0.0) -> Optional[str]:
        """Feed every frame. Returns the active pattern (sustained >= SUSTAIN_S) or None."""
        if not on_screen:
            self._since.clear()
            self.current = None
            return None
        self._span_s += dt
        if t - self._last_sample < SAMPLE_EVERY_S:
            return self.current                       # judged once a second
        self._last_sample = t
        self._samples.append((t, distance_cm, pitch, roll, yaw))
        while self._samples and t - self._samples[0][0] > BASELINE_S:
            self._samples.popleft()
        if self._span_s < MIN_BASELINE_S or len(self._samples) < 30:
            return None
        recent = [s for s in self._samples if t - s[0] <= SHORT_S]
        if len(recent) < 5:
            return None
        base_dist = self._baseline_distance(t)
        base_pitch = self._baseline_pitch(yaw)
        dists = [s[1] for s in recent if s[1]]
        flags = {
            "leaning_in": bool(base_dist and dists and
                               statistics.median(dists) < LEAN_RATIO * base_dist),
            "chin_down": base_pitch is not None and
            statistics.median(s[2] for s in recent) < base_pitch - CHIN_DOWN_DEG,
            "head_tilt": abs(statistics.median(s[3] for s in recent)) >= TILT_DEG,
        }
        for k, on in flags.items():
            if on:
                self._since.setdefault(k, t)
            else:
                self._since.pop(k, None)
        active = [k for k in ("leaning_in", "chin_down", "head_tilt")
                  if k in self._since and t - self._since[k] >= SUSTAIN_S]
        self.current = active[0] if active else None
        return self.current

    def _baseline_distance(self, t: float) -> Optional[float]:
        if t - self._base_dist[0] >= 30.0:            # recompute every 30 s
            d = sorted(s[1] for s in self._samples if s[1])
            self._base_dist = (t, d[int(0.8 * (len(d) - 1))] if len(d) >= 30 else None)
        return self._base_dist[1]

    def _baseline_pitch(self, yaw: float) -> Optional[float]:
        p = sorted(s[2] for s in self._samples if abs(s[4] - yaw) <= 10.0)
        return p[int(0.7 * (len(p) - 1))] if len(p) >= 30 else None

    def held_for(self, t: float) -> float:
        """How long the current pattern has lasted."""
        if self.current is None:
            return 0.0
        return t - self._since.get(self.current, t)

    def baseline_distance(self) -> Optional[float]:
        return self._base_dist[1]

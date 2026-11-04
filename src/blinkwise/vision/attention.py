"""Where is the user looking? Screen zones from head pose.

A webcam can't see your monitors, but it can see your head. People with
several screens settle into a few stable head orientations ("zones"), one per
screen they actually use. We build a time-weighted histogram of head yaw over
the last few minutes and find its peaks.

This tells us:
  * how many screens are *actually in use* (vs. merely connected),
  * how time splits between them and how often the user switches,
  * how far the head has to turn for each (neck strain, exposure),
  * per-zone blink rates (people often blink far less on one screen, e.g. the
    one with code or a game on it).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple

import numpy as np

YAW_MIN, YAW_MAX, BIN_DEG = -70.0, 70.0, 2.0
N_BINS = int((YAW_MAX - YAW_MIN) / BIN_DEG)


@dataclass
class Zone:
    index: int
    center_yaw: float
    mean_pitch: float
    share: float                 # fraction of attended time in this zone
    blink_rate: Optional[float]  # blinks/min while looking here (None if too little data)
    observed_s: float


@dataclass
class _Sample:
    t: float
    dt: float
    yaw: float
    pitch: float
    blinks: int = 0


@dataclass
class AttentionTracker:
    horizon_s: float = 600.0          # look at the last 10 minutes
    min_share: float = 0.10           # a zone must hold >= 10% of the time
    min_separation_deg: float = 14.0  # two monitors side by side are typically >= 20 deg apart
    away_yaw_deg: float = 55.0        # beyond this the user isn't looking at a screen
    switch_dwell_s: float = 1.0       # a zone switch must last this long to count
    _samples: Deque[_Sample] = field(default_factory=deque)
    _obs: float = 0.0
    _zones: List[Zone] = field(default_factory=list)
    _zones_at: float = -1e9
    _current: Optional[int] = None
    _candidate: Optional[Tuple[int, float]] = None
    _switches: Deque[float] = field(default_factory=deque)

    def attending(self, face: bool, yaw: float) -> bool:
        return face and abs(yaw) < self.away_yaw_deg

    def update(self, t: float, dt: float, face: bool, yaw: float, pitch: float) -> None:
        if not self.attending(face, yaw):
            return
        self._samples.append(_Sample(t, dt, yaw, pitch))
        self._obs += dt
        while self._samples and t - self._samples[0].t > self.horizon_s:
            self._obs -= self._samples.popleft().dt
        if t - self._zones_at > 5.0:            # recluster every few seconds
            self._zones = self._cluster()
            self._zones_at = t
        self._track_switch(t, yaw)

    def add_blink(self) -> None:
        if self._samples:
            self._samples[-1].blinks += 1

    @property
    def zones(self) -> List[Zone]:
        return self._zones

    @property
    def current_zone(self) -> Optional[int]:
        return self._current

    def switches_per_min(self, now: float, window_s: float = 300.0) -> float:
        while self._switches and now - self._switches[0] > window_s:
            self._switches.popleft()
        span = min(window_s, self.observed_s())
        return len(self._switches) / (span / 60.0) if span >= 60 else 0.0

    def observed_s(self) -> float:
        return max(0.0, self._obs)          # running total (summing 14k samples was the hot spot)

    # -- internals ------------------------------------------------------------
    def _zone_of(self, yaw: float) -> Optional[int]:
        if not self._zones:
            return None
        best = min(self._zones, key=lambda z: abs(z.center_yaw - yaw))
        return best.index if abs(best.center_yaw - yaw) <= self.min_separation_deg else None

    def _track_switch(self, t: float, yaw: float) -> None:
        z = self._zone_of(yaw)
        if z is None or z == self._current:
            self._candidate = None
            return
        if self._current is None:
            self._current = z
            return
        if self._candidate is None or self._candidate[0] != z:
            self._candidate = (z, t)
        elif t - self._candidate[1] >= self.switch_dwell_s:
            self._current = z
            self._candidate = None
            self._switches.append(t)

    def _cluster(self) -> List[Zone]:
        if not self._samples:
            return []
        yaws = np.array([s.yaw for s in self._samples])
        w = np.array([s.dt for s in self._samples])
        total = w.sum()
        if total < 30:                      # need 30 s of data
            return []
        hist, edges = np.histogram(yaws, bins=N_BINS, range=(YAW_MIN, YAW_MAX), weights=w)
        centers = (edges[:-1] + edges[1:]) / 2
        # Gaussian smoothing (sigma ~ 3 deg) to merge jitter within a screen.
        k = np.exp(-0.5 * (np.arange(-6, 7) * BIN_DEG / 3.0) ** 2)
        smooth = np.convolve(hist, k / k.sum(), mode="same")
        peaks = [i for i in range(1, N_BINS - 1)
                 if smooth[i] >= smooth[i - 1] and smooth[i] > smooth[i + 1]]
        peaks.sort(key=lambda i: -smooth[i])
        chosen: List[int] = []
        for i in peaks:
            if all(abs(centers[i] - centers[j]) >= self.min_separation_deg for j in chosen):
                chosen.append(i)
        chosen.sort()
        if not chosen:
            return []
        # Assign each sample to the nearest chosen peak; drop zones with little time.
        cy = centers[chosen]
        assign = np.abs(yaws[:, None] - cy[None, :]).argmin(axis=1)
        zones = []
        for zi in range(len(cy)):
            mask = assign == zi
            share = float(w[mask].sum() / total)
            if share < self.min_share:
                continue
            obs = float(w[mask].sum())
            blinks = sum(s.blinks for s, m in zip(self._samples, mask, strict=True) if m)
            pitch = float(np.average([s.pitch for s, m in zip(self._samples, mask, strict=True) if m],
                                     weights=w[mask]))
            yaw_c = float(np.average(yaws[mask], weights=w[mask]))
            zones.append(Zone(index=0, center_yaw=yaw_c, mean_pitch=pitch, share=share,
                              blink_rate=(blinks / obs * 60.0) if obs >= 60 else None,
                              observed_s=obs))
        # Renormalise shares after dropping tiny zones; index left-to-right.
        s = sum(z.share for z in zones) or 1.0
        for i, z in enumerate(sorted(zones, key=lambda z: z.center_yaw)):
            z.index, z.share = i, z.share / s
        return sorted(zones, key=lambda z: z.index)


def connected_monitors() -> Optional[int]:
    """Number of connected displays, if the optional `screeninfo` package can tell."""
    try:
        from screeninfo import get_monitors
        n = len(get_monitors())
        return n or None
    except Exception:
        return None


def angle_between(a: float, b: float) -> float:
    return abs(math.remainder(a - b, 360.0))

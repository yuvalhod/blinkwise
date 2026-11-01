"""Online blink detection from eye aspect ratios.

Why not a fixed EAR threshold (the textbook approach)?
  * Open-eye EAR differs a lot between people (eye shape, glasses, camera angle).
  * EAR drops for seconds at a time when you look *down* at a keyboard or phone
    (the upper lid follows the gaze), which a fixed threshold counts as a blink.
  * Head movement makes EAR drift slowly; blinks often happen *during* head
    movements (they accompany gaze shifts), so you can't just ignore those.

Approach
  1. Normalise each eye by its own rolling open level:
         openness o(t) = EAR(t) / high-quantile(EAR over the last few seconds)
     and fuse the two eyes weighted by how squarely each faces the camera.
  2. A blink is a *prominent local minimum* of o(t): the lids drop and come back
     within ~half a second. We look a short time before and after each minimum
     (a fixed ~0.45 s latency, irrelevant for coaching) and require the dip to
     be deep relative to *both* sides. Slow drifts and sustained downward gaze
     have no prominence on one side and are rejected without special cases.
  3. Dip width at half prominence ~ blink duration; long closures (>0.5 s) are
     flagged as fatigue signals.
  4. Closure depth relative to the surrounding open level classifies complete
     vs. incomplete blinks. Symptoms of computer vision syndrome correlate with
     the percentage of incomplete blinks, not just rate (Portello, Rosenfield &
     Chu 2013). That needs enough temporal resolution to sample the bottom of a
     ~100-150 ms closure, so completeness is only reported at >= 20 fps.

Validated against hand-labelled real video in tests/data (see scripts/eval_blinks.py).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import numpy as np

from .features import FrameFeatures


@dataclass
class Blink:
    t: float                  # time of deepest closure
    start: float              # half-prominence crossing before the minimum
    end: float                # half-prominence crossing after the minimum
    duration: float           # seconds (approx. lid-closed time)
    closure: float            # 0..1 depth relative to the surrounding open level
    complete: Optional[bool]  # None if the frame rate is too low to judge
    long: bool                # unusually long closure (fatigue signal)


@dataclass
class BlinkParams:
    window_s: float = 3.0           # rolling window for each eye's open-level baseline
    open_quantile: float = 0.8
    warmup_s: float = 0.75          # history needed before detecting
    before_s: float = 0.5           # look this far back for the pre-blink open level
    after_s: float = 0.7            # ...and this far ahead for the re-opened level (= latency)
    local_s: float = 0.15           # the minimum must be the lowest point within +/- this
    min_prominence: float = 0.20    # dip depth in openness units (1.0 = open eye)...
    min_rel_prominence: float = 0.25  # ...and relative to the surrounding open level
    complete_closure: float = 0.6   # closure depth >= this is a complete blink
    max_blink_s: float = 0.5        # spontaneous blinks are ~100-400 ms
    max_event_s: float = 1.0        # wider dips are eye closures / gaze changes, not blinks
    max_pitch_shift: float = 8.0    # deg; head pitch at the dip vs. just outside it. A shallow
    deep_closure: float = 0.6       # dip with a big pitch shift is a glance down, not a blink.
    max_abs_yaw: float = 40.0       # beyond this the far eye is unreliable -> pause
    max_gap_s: float = 0.4          # a gap this long (face lost) splits the signal
    refractory_s: float = 0.15
    min_fps_for_completeness: float = 20.0


class _Baseline:
    def __init__(self, window_s: float, q: float):
        self.window_s, self.q = window_s, q
        self.buf: Deque[Tuple[float, float]] = deque()

    def push(self, t: float, v: float) -> None:
        self.buf.append((t, v))
        while self.buf and t - self.buf[0][0] > self.window_s:
            self.buf.popleft()

    def span(self) -> float:
        return self.buf[-1][0] - self.buf[0][0] if len(self.buf) > 1 else 0.0

    def value(self) -> float:
        return float(np.quantile([v for _, v in self.buf], self.q)) if self.buf else 0.0

    def clear(self) -> None:
        self.buf.clear()


class BlinkDetector:
    """Feed FrameFeatures in time order; returns a Blink when one is confirmed."""

    def __init__(self, params: Optional[BlinkParams] = None):
        self.p = params or BlinkParams()
        self._base_r = _Baseline(self.p.window_s, self.p.open_quantile)
        self._base_l = _Baseline(self.p.window_s, self.p.open_quantile)
        self._sig: List[Tuple[float, float, float]] = []  # (t, openness, pitch) recent history
        self._next = 0                                # index of next candidate to evaluate
        self._fps_dt: Optional[float] = None
        self._last_t: Optional[float] = None
        self._last_blink_t = -1e9
        self._last_blink_end = -1e9
        self.openness: Optional[float] = None         # latest value, for UIs/debugging

    @property
    def fps(self) -> float:
        return 1.0 / self._fps_dt if self._fps_dt else 0.0

    def reset(self) -> None:
        self._base_r.clear()
        self._base_l.clear()
        self._sig.clear()
        self._next = 0
        self._last_t = None
        self.openness = None

    def update(self, f: FrameFeatures) -> Optional[Blink]:
        p = self.p
        if self._last_t is not None:
            dt = f.t - self._last_t
            if 0 < dt < 1.0:
                self._fps_dt = dt if self._fps_dt is None else 0.9 * self._fps_dt + 0.1 * dt
            if dt > p.max_gap_s:
                self._sig.clear()
                self._next = 0
        self._last_t = f.t

        if not f.face or abs(f.yaw) > p.max_abs_yaw or f.ear_right <= 0 or f.ear_left <= 0:
            # Unusable frame: flush what we can judge, then break the signal.
            self.openness = None
            out = self._evaluate(final=True)
            self._sig.clear()
            self._next = 0
            return out

        self._base_r.push(f.t, f.ear_right)
        self._base_l.push(f.t, f.ear_left)
        if self._base_r.span() < p.warmup_s:
            return None
        o = self._openness(f)
        self.openness = o
        self._sig.append((f.t, o, f.pitch))
        out = self._evaluate(final=False)
        # Trim history we no longer need (keep enough look-back for the next candidates).
        horizon = f.t - (p.before_s + p.after_s + p.max_event_s)
        drop = 0
        while drop < self._next and self._sig[drop][0] < horizon:
            drop += 1
        if drop:
            del self._sig[:drop]
            self._next -= drop
        return out

    def recent_min_openness(self, seconds: float) -> Optional[float]:
        """Lowest openness in the last `seconds` (detects a blink not yet confirmed)."""
        if not self._sig:
            return None
        t_now = self._sig[-1][0]
        return min(o for t, o, _ in self._sig if t_now - t <= seconds)

    # -- internals ------------------------------------------------------------
    def _openness(self, f: FrameFeatures) -> float:
        br, bl = self._base_r.value(), self._base_l.value()
        o_r = f.ear_right / br if br > 1e-6 else 1.0
        o_l = f.ear_left / bl if bl > 1e-6 else 1.0
        # Weight each eye by how squarely it faces the camera (apparent width^2):
        # with a turned head the far eye is foreshortened and its landmarks noisier.
        wr, wl = f.width_right ** 2, f.width_left ** 2
        if wr + wl <= 0:
            return (o_r + o_l) / 2
        return (o_r * wr + o_l * wl) / (wr + wl)

    def _evaluate(self, final: bool) -> Optional[Blink]:
        """Judge every candidate old enough to have its full look-ahead window."""
        p, sig = self.p, self._sig
        if not sig:
            return None
        t_now = sig[-1][0]
        result = None
        while self._next < len(sig):
            tk = sig[self._next][0]
            if not final and t_now - tk < p.after_s:
                break
            k = self._next
            self._next += 1
            b = self._judge(k)
            if b is not None and result is None:
                result = b
                self._last_blink_t = b.t
                self._last_blink_end = b.end
        return result

    def _judge(self, k: int) -> Optional[Blink]:
        p, sig = self.p, self._sig
        tk, ok, pk = sig[k]
        if tk - self._last_blink_t < p.refractory_s or tk <= self._last_blink_end:
            return None
        # Must be the lowest point locally (first one wins on ties).
        for j in range(len(sig)):
            tj, oj = sig[j][0], sig[j][1]
            if abs(tj - tk) <= p.local_s and (oj < ok or (oj == ok and j < k)):
                return None
        left = [o for t, o, _ in sig if tk - p.before_s <= t < tk]
        right = [o for t, o, _ in sig if tk < t <= tk + p.after_s]
        if not left or not right:
            return None
        ref = min(max(left), max(right))
        prom = ref - ok
        if prom < p.min_prominence or prom < p.min_rel_prominence * ref:
            return None
        # Width at half prominence ~ how long the lids were down.
        half = ok + prom / 2
        start = end = tk
        j_before, j_after = k, k
        for j in range(k - 1, -1, -1):
            j_before = j
            if sig[j][1] > half:
                break
            start = sig[j][0]
        for j in range(k + 1, len(sig)):
            j_after = j
            if sig[j][1] > half:
                break
            end = sig[j][0]
        frame_dt = self._fps_dt or 0.033
        duration = (end - start) + frame_dt
        if duration > p.max_event_s:
            return None
        closure = float(np.clip(prom / ref, 0.0, 1.0))
        pitch_shift = max(abs(pk - sig[j_before][2]), abs(pk - sig[j_after][2]))
        if pitch_shift > p.max_pitch_shift and closure < p.deep_closure:
            return None   # lids followed the gaze down (keyboard/phone), not a blink
        complete = None
        if self.fps >= p.min_fps_for_completeness:
            complete = closure >= p.complete_closure
        return Blink(t=tk, start=start, end=end, duration=duration, closure=closure,
                     complete=complete, long=duration > p.max_blink_s)

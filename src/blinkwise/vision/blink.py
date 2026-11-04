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

import math
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
    min_rel_prominence: float = 0.20  # ...and relative to the surrounding open level
    complete_closure: float = 0.6   # closure depth >= this is a complete blink
    max_blink_s: float = 0.5        # spontaneous blinks are ~100-400 ms
    max_event_s: float = 1.0        # wider dips are eye closures / gaze changes, not blinks
    max_pitch_shift: float = 8.0    # deg; head pitch at the dip vs. just outside it. A shallow
    deep_closure: float = 0.6       # dip with a big pitch shift is a glance down, not a blink.
    max_abs_yaw: float = 40.0       # beyond this the far eye is unreliable -> pause
    max_gap_s: float = 0.4          # a gap this long (face lost) splits the signal
    refractory_s: float = 0.15
    min_fps_for_completeness: float = 20.0
    noise_k: float = 5.0            # dips must also exceed this many noise sigmas...
    noise_window_s: float = 5.0     # ...estimated over this window
    smooth_min_fps: float = 20.0    # median-of-3 smoothing when frames are this dense
    vis_window_s: float = 1.5       # eye visibility is a rolling median (a blink hides the iris briefly)
    vis_hidden: float = 0.02        # iris contrast below this = eye hidden (sunglasses, glare)
    vis_full: float = 0.04          # ...at or above this the eye gets full weight
    closed_ear_ratio: float = 0.45  # EAR this far below the open level = lids closed, not hidden
    hidden_min_s: float = 1.0       # both eyes must stay hidden this long to pause detection


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
        """Same as np.quantile(..., method="linear"), ~10x faster for these small windows."""
        if not self.buf:
            return 0.0
        vals = sorted(v for _, v in self.buf)
        pos = self.q * (len(vals) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(vals) - 1)
        return float(vals[lo] + (vals[hi] - vals[lo]) * (pos - lo))

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
        self._pending: Deque[Blink] = deque()          # confirmed, not yet returned
        self._raw3: Deque[float] = deque(maxlen=3)     # for median-of-3 smoothing
        self._smooth = False
        self._diffs: Deque[Tuple[float, float]] = deque()  # (t, |d openness|) for noise
        self._prev_o: Optional[float] = None
        self._vis_r: Deque[Tuple[float, float]] = deque()
        self._vis_l: Deque[Tuple[float, float]] = deque()
        self._open_ref: Optional[float] = None         # slow open-eye EAR reference
        self._ref_t: Optional[float] = None
        self._hidden_since: Optional[float] = None
        self.eyes_hidden = False                        # both eyes covered (not just closed)
        self.vis_right: Optional[float] = None
        self.vis_left: Optional[float] = None
        self.openness: Optional[float] = None         # latest value, for UIs/debugging

    @property
    def fps(self) -> float:
        return 1.0 / self._fps_dt if self._fps_dt else 0.0

    def reset(self) -> None:
        self._base_r.clear()
        self._base_l.clear()
        self._sig.clear()
        self._next = 0
        self._pending.clear()
        self._last_t = None
        self.openness = None

    def update(self, f: FrameFeatures) -> Optional[Blink]:
        p = self.p
        if self._last_t is not None:
            dt = f.t - self._last_t
            if 0 < dt < 1.0:
                self._fps_dt = dt if self._fps_dt is None else 0.9 * self._fps_dt + 0.1 * dt
            if dt > p.max_gap_s:
                self._break_signal()
        self._last_t = f.t

        if not f.face or abs(f.yaw) > p.max_abs_yaw or f.ear_right <= 0 or f.ear_left <= 0:
            # Unusable frame: judge what we can, then break the signal.
            self.openness = None
            self._break_signal()
            return self._pending.popleft() if self._pending else None

        if self._update_visibility(f):
            # Both eyes hidden (sunglasses, glare): the landmarks are guesses. Pause.
            self.openness = None
            self._break_signal()
            return self._pending.popleft() if self._pending else None

        self._base_r.push(f.t, f.ear_right)
        self._base_l.push(f.t, f.ear_left)
        if self._base_r.span() < p.warmup_s:
            return None
        o = self._openness(f)
        self.openness = o
        self._track_noise(f.t, o)
        # Median-of-3 at high frame rates. The buffer is always kept current, and switching
        # has hysteresis: a frame-rate estimate wobbling around the threshold used to flip
        # smoothing on with stale samples in the buffer, creating one-frame fake dips.
        self._raw3.append(o)
        if self.fps >= p.smooth_min_fps - 0.5:
            self._smooth = True
        elif self.fps < p.smooth_min_fps - 3.0:
            self._smooth = False
        if self._smooth and len(self._raw3) == 3:
            o = sorted(self._raw3)[1]
        self._sig.append((f.t, o, f.pitch))
        self._evaluate(final=False)
        out = self._pending.popleft() if self._pending else None
        # Trim history we no longer need (keep enough look-back for the next candidates).
        horizon = f.t - (p.before_s + p.after_s + p.max_event_s)
        drop = 0
        while drop < self._next and self._sig[drop][0] < horizon:
            drop += 1
        if drop:
            del self._sig[:drop]
            self._next -= drop
        return out

    def flush(self) -> List[Blink]:
        """End of stream: judge remaining candidates with whatever look-ahead exists."""
        self._break_signal()
        out = list(self._pending)
        self._pending.clear()
        return out

    def _break_signal(self) -> None:
        self._evaluate(final=True)
        self._sig.clear()
        self._next = 0
        self._raw3.clear()
        self._prev_o = None

    @property
    def noise(self) -> Optional[float]:
        """Robust per-frame noise of the openness signal (sigma), or None if unknown.

        Median absolute frame-to-frame change, scaled to a Gaussian sigma. Blinks are a
        small fraction of frames, so the median ignores them.
        """
        if len(self._diffs) < 20:
            return None
        return float(np.median([d for _, d in self._diffs])) * 1.4826 / math.sqrt(2)

    def _track_noise(self, t: float, o: float) -> None:
        if self._prev_o is not None:
            self._diffs.append((t, abs(o - self._prev_o)))
            while self._diffs and t - self._diffs[0][0] > self.p.noise_window_s:
                self._diffs.popleft()
        self._prev_o = o

    def _min_prominence(self) -> float:
        n = self.noise
        return self.p.min_prominence if n is None else max(self.p.min_prominence, self.p.noise_k * n)

    def recent_min_openness(self, seconds: float) -> Optional[float]:
        """Lowest openness in the last `seconds` (detects a blink not yet confirmed)."""
        if not self._sig:
            return None
        t_now = self._sig[-1][0]
        return min(o for t, o, _ in self._sig if t_now - t <= seconds)

    # -- internals ------------------------------------------------------------
    def _update_visibility(self, f: FrameFeatures) -> bool:
        """Track per-eye visibility; return True if both eyes are hidden (pause detection)."""
        p = self.p
        self.vis_right = _rolling_median(self._vis_r, f.t, f.vis_right, p.vis_window_s)
        self.vis_left = _rolling_median(self._vis_l, f.t, f.vis_left, p.vis_window_s)
        ear = (f.ear_right + f.ear_left) / 2
        # Slow reference for "open": decays ~0.5%/s so it can follow pose/lighting changes.
        if self._open_ref is None:
            self._open_ref = ear
        else:
            decay = 0.995 ** max(0.0, f.t - (self._ref_t or f.t))
            self._open_ref = max(ear, self._open_ref * decay)
        self._ref_t = f.t
        closed = ear < p.closed_ear_ratio * self._open_ref
        hidden_now = (self.vis_right is not None and self.vis_left is not None and not closed
                      and self.vis_right < p.vis_hidden and self.vis_left < p.vis_hidden)
        if not hidden_now:
            self._hidden_since = None
        elif self._hidden_since is None:
            self._hidden_since = f.t
        self.eyes_hidden = (self._hidden_since is not None
                            and f.t - self._hidden_since >= p.hidden_min_s)
        return self.eyes_hidden

    def _openness(self, f: FrameFeatures) -> float:
        br, bl = self._base_r.value(), self._base_l.value()
        o_r = f.ear_right / br if br > 1e-6 else 1.0
        o_l = f.ear_left / bl if bl > 1e-6 else 1.0
        # Weight each eye by how squarely it faces the camera (apparent width^2):
        # with a turned head the far eye is foreshortened and its landmarks noisier.
        # And by how visible it is: a covered eye's landmarks are guesses.
        wr, wl = f.width_right ** 2, f.width_left ** 2
        if self.vis_right is not None and self.vis_left is not None:
            wr *= min(1.0, max(0.05, self.vis_right / self.p.vis_full))
            wl *= min(1.0, max(0.05, self.vis_left / self.p.vis_full))
        if wr + wl <= 0:
            return (o_r + o_l) / 2
        return (o_r * wr + o_l * wl) / (wr + wl)

    def _evaluate(self, final: bool) -> None:
        """Judge every candidate old enough to have its full look-ahead window."""
        p, sig = self.p, self._sig
        if not sig:
            return
        t_now = sig[-1][0]
        while self._next < len(sig):
            tk = sig[self._next][0]
            if not final and t_now - tk < p.after_s:
                break
            k = self._next
            self._next += 1
            b = self._judge(k)
            if b is not None:
                self._pending.append(b)
                self._last_blink_t = b.t
                self._last_blink_end = b.end

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
        if prom < self._min_prominence() or prom < p.min_rel_prominence * ref:
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


def _rolling_median(buf: Deque[Tuple[float, float]], t: float, v: Optional[float],
                    window: float) -> Optional[float]:
    if v is not None:
        buf.append((t, v))
    while buf and t - buf[0][0] > window:
        buf.popleft()
    if not buf:
        return None
    vals = sorted(x for _, x in buf)
    return vals[len(vals) // 2]

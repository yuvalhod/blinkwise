"""A synthetic screen user, for tests and the camera-free `blinkwise demo`.

Generates FrameFeatures with known ground truth: blinks (complete, incomplete
and long), saccades between several screens, glances down at the keyboard,
leaving the desk, and measurement noise.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Sequence, Tuple

from ..vision.features import FrameFeatures


@dataclass
class Screen:
    yaw: float
    pitch: float = -4.0
    share: float = 1.0


@dataclass
class Scenario:
    duration_s: float = 600.0
    fps: float = 30.0
    blink_rate: float = 8.0               # per minute
    incomplete_frac: float = 0.2
    long_frac: float = 0.0
    long_hold_s: float = 0.6              # how long "long" blinks stay closed
    screens: Sequence[Screen] = (Screen(0.0),)
    dwell_s: float = 25.0                 # mean time on a screen before switching
    keyboard_glances_per_min: float = 0.0
    away: Sequence[Tuple[float, float]] = ()   # (start, end) seconds with no face
    distance_cm: float = 60.0
    luminance: float = 110.0
    ear_open: float = 0.30
    ear_noise: float = 0.008
    pose_noise_deg: float = 1.0
    phone: Sequence[Tuple[float, float]] = ()  # (start, end) looking down at a phone
    phone_blink_factor: float = 1.0           # blink-rate multiplier while on the phone
    decay_per_hour: float = 0.0               # blink rate falls this fraction per hour of
                                              # continuous use (resets after 2+ min away)
    blink_times: Sequence[float] = ()         # scripted blinks (replaces the random ones)
    blink_depth: Optional[Tuple[float, float]] = None  # remaining openness at the bottom
    glance_windows: Sequence[Tuple[float, float]] = ()  # scripted looks at the keyboard
    seed: int = 7


@dataclass
class TruthBlink:
    t: float          # middle of the closed phase
    complete: bool
    long: bool


@dataclass
class Simulation:
    scenario: Scenario
    truth: List[TruthBlink] = field(default_factory=list)

    def _rate_factor(self, t: float) -> float:
        """Thinning factor for the blink process at time t (<= 1)."""
        sc = self.scenario
        f = 1.0
        if sc.decay_per_hour:
            start = 0.0
            for a, b in sc.away:
                if b <= t and b - a >= 120:
                    start = max(start, b)
            f *= max(0.3, 1.0 - sc.decay_per_hour * (t - start) / 3600.0)
        if sc.phone and any(a <= t < b for a, b in sc.phone):
            f *= sc.phone_blink_factor
        return min(1.0, f)

    def frames(self) -> Iterator[FrameFeatures]:
        sc = self.scenario
        rng = random.Random(sc.seed)
        n = int(sc.duration_s * sc.fps)
        # --- schedule blinks (Poisson with a 0.6 s refractory gap) ---
        self.truth = [TruthBlink(bt, True, False) for bt in sc.blink_times]
        t = rng.expovariate(sc.blink_rate / 60.0) + 1.5
        while not sc.blink_times and t < sc.duration_s - 1:
            complete = rng.random() >= sc.incomplete_frac
            is_long = rng.random() < sc.long_frac
            if not any(a <= t <= b + 1.0 for a, b in sc.away) and rng.random() < self._rate_factor(t):
                self.truth.append(TruthBlink(t, complete, is_long))
                t += sc.long_hold_s if is_long else 0.0
            t += max(0.6, rng.expovariate(sc.blink_rate / 60.0))
        blinks = [(b, rng.uniform(*sc.blink_depth) if sc.blink_depth else
                   rng.uniform(0.05, 0.15) if b.complete else rng.uniform(0.45, 0.65))
                  for b in self.truth]
        # --- schedule screen dwell periods ---
        shares = [s.share for s in sc.screens]
        plan: List[Tuple[float, Screen]] = []
        t = 0.0
        while t < sc.duration_s:
            plan.append((t, rng.choices(list(sc.screens), weights=shares)[0]))
            t += rng.expovariate(1.0 / sc.dwell_s) + 2.0
        # --- keyboard glances (look down ~0.8-2 s) ---
        glances: List[Tuple[float, float]] = list(sc.glance_windows)
        if sc.keyboard_glances_per_min > 0:
            t = rng.expovariate(sc.keyboard_glances_per_min / 60.0)
            while t < sc.duration_s:
                glances.append((t, t + rng.uniform(0.8, 2.0)))
                t += rng.expovariate(sc.keyboard_glances_per_min / 60.0) + 2.0
        # Per-eye person variation.
        base_r = sc.ear_open * rng.uniform(0.95, 1.05)
        base_l = sc.ear_open * rng.uniform(0.95, 1.05)
        bi = pi = 0
        yaw_s = pitch_s = None
        for i in range(n):
            t = i / sc.fps
            if any(a <= t < b for a, b in sc.away):
                yield FrameFeatures(t=t, face=False)
                continue
            while pi + 1 < len(plan) and plan[pi + 1][0] <= t:
                pi += 1
            target = plan[pi][1]
            down = any(a <= t < b for a, b in glances)
            on_phone = any(a <= t < b for a, b in sc.phone)
            ty = target.yaw
            tp = target.pitch - (35.0 if on_phone else 25.0 if down else 0.0)
            # Saccade/head movement: fast exponential approach (~120 ms time constant).
            a = 1 - math.exp(-1.0 / (sc.fps * 0.12))
            yaw_s = ty if yaw_s is None else yaw_s + (ty - yaw_s) * a
            pitch_s = tp if pitch_s is None else pitch_s + (tp - pitch_s) * a
            # Lid follows gaze: looking down lowers the upper lid.
            gaze_factor = 1.0 + max(-0.45, min(0.15, pitch_s / 55.0))
            lid = 1.0
            while bi < len(blinks) and blinks[bi][0].t < t - 1.0:
                bi += 1
            for b, depth in blinks[bi:bi + 3]:
                lid = min(lid, _lid_profile(t - b.t, depth, b.long, sc.long_hold_s))
            yaw_n = yaw_s + rng.gauss(0, sc.pose_noise_deg)
            # Foreshortening: the far eye looks narrower when the head turns.
            wr = 30.0 * math.cos(math.radians(max(0.0, yaw_n) * 0.9))
            wl = 30.0 * math.cos(math.radians(max(0.0, -yaw_n) * 0.9))
            yield FrameFeatures(
                t=t, face=True,
                ear_right=max(0.01, base_r * gaze_factor * lid + rng.gauss(0, sc.ear_noise)),
                ear_left=max(0.01, base_l * gaze_factor * lid + rng.gauss(0, sc.ear_noise)),
                width_right=wr, width_left=wl,
                yaw=yaw_n, pitch=pitch_s + rng.gauss(0, sc.pose_noise_deg), roll=0.0,
                distance_cm=sc.distance_cm + rng.gauss(0, 1.5),
                luminance=sc.luminance + rng.gauss(0, 2.0),
                faces=1, vis_right=0.07, vis_left=0.07,
                face_px=15.0 * 554.0 / sc.distance_cm,   # 15 cm face, 640 px / 60 deg camera
            )


def _lid_profile(dt: float, depth: float, long: bool, long_hold_s: float = 0.6) -> float:
    """Openness multiplier around a blink centred at dt=0.

    Closing ~75 ms, brief hold, re-opening ~150 ms (re-opening is slower than
    closing in real blinks). `depth` is the remaining openness at the bottom.
    """
    close, hold, reopen = 0.075, (long_hold_s if long else 0.03), 0.15
    dt += hold / 2            # dt=0 is the middle of the closed phase
    if dt < -close or dt > hold + reopen:
        return 1.0
    if dt < 0:
        return 1.0 - (1.0 - depth) * (1 + dt / close)
    if dt <= hold:
        return depth
    return depth + (1.0 - depth) * ((dt - hold) / reopen)


def demo_phone_schedule(duration_s: float) -> List[Tuple[float, float]]:
    """Phone use for the demo: a 3-minute phone session every 40 minutes, and a 10-minute
    'multitasking' stretch every 25 minutes (30 s phone glances every 90 s)."""
    out: List[Tuple[float, float]] = []
    t = 15 * 60.0
    while t < duration_s:
        out += [(t + k * 90.0, t + k * 90.0 + 30.0) for k in range(7)]
        t += 25 * 60
    t = 30 * 60.0
    while t < duration_s:
        out.append((t, t + 180.0))
        t += 40 * 60
    return sorted(out)


def demo_scenario(seed: Optional[int] = None) -> Scenario:
    """A plausible two-monitor knowledge worker who forgets to blink and checks their phone."""
    dur = 3600 * 8
    return Scenario(duration_s=dur, fps=24, blink_rate=7.0, incomplete_frac=0.35,
                    long_frac=0.02, screens=(Screen(-4, -5, 0.65), Screen(31, -3, 0.35)),
                    keyboard_glances_per_min=1.0, distance_cm=46,
                    phone=demo_phone_schedule(dur), phone_blink_factor=0.7,
                    seed=seed if seed is not None else random.randrange(1 << 30))

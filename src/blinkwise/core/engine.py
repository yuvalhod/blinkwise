"""The engine: FrameFeatures in, events out.

It has no I/O and no clock of its own, so it behaves identically on a live
camera, a recorded video or the synthetic simulator (which is how it's tested).
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

from ..config import Settings
from ..research import RELAXED_BLINK_RATE
from ..vision.attention import AttentionTracker, connected_monitors
from ..vision.blink import Blink, BlinkDetector, BlinkParams
from ..vision.features import FrameFeatures
from ..vision.quality import Quality, assess
from .breaks import BreakScheduler
from .coach import Coach, CoachContext
from .events import BlinkEvent, BreakDue, BreakEnded, MinuteSummary, StareCue, Suggestion
from .metrics import RollingStats

AWAY_RESET_S = 2.0          # after this long without seeing the eyes, assume they blinked
DOWN_DEG = 18.0             # head this far below your screen pitch = phone/desk/paper
CONTINUOUS_RESET_S = 120.0  # away this long ends a continuous-use session
REST_OPENNESS = 0.5         # eyes this closed for a while = resting them (counts as a break)
PERCLOS_OPENNESS = 0.2      # PERCLOS counts time with lids >= 80% closed (P80)
PERCLOS_MAX_RUN_S = 5.0     # closures longer than this are deliberate rest, not drowsiness


@dataclass
class _Minute:
    start: float
    observed: float = 0.0
    blinks: int = 0
    judged: int = 0
    incomplete: int = 0
    long: int = 0
    max_stare: float = 0.0
    session_min: float = 0.0     # continuous screen minutes at the start of this minute
    down_s: float = 0.0          # looking well below the screen (phone, tablet, paper)
    obs_down_s: float = 0.0      # ...with the eyes measurable
    blinks_down: int = 0
    device_switches: int = 0     # screen <-> looking down transitions
    stares20: int = 0            # stares of 20 s or more


class Engine:
    def __init__(self, settings: Optional[Settings] = None, monitors: Optional[int] = -1,
                 blink_params: Optional[BlinkParams] = None):
        self.s = settings or Settings()
        self.detector = BlinkDetector(blink_params)
        self.stats = RollingStats()
        self.attention = AttentionTracker()
        self.breaks = BreakScheduler(self.s.micro_break_minutes, self.s.micro_break_seconds,
                                     self.s.long_break_minutes, self.s.long_break_seconds,
                                     self.s.adaptive_breaks)
        self.coach = Coach(self.s)
        self.monitors = connected_monitors() if monitors == -1 else monitors

        self._t0: Optional[float] = None
        self._last_t: Optional[float] = None
        self._last_seen: Optional[float] = None
        self._last_blink_t: Optional[float] = None
        self._last_cue_t = -1e9
        self._closed_run = 0.0
        self._hidden: Deque[Tuple[float, bool]] = deque()    # eyes-hidden flags, last 60 s
        self._continuous_s = 0.0      # screen time since the last real (2 min+) break
        self._away_run = 0.0
        self._down_now = False
        self._down_since: Optional[float] = None
        self._stare20_counted = False
        self._p80_run = 0.0          # current >=80%-closed run (pending until the eyes reopen)
        self._last_coach_t = -1e9
        self._screen_s = 0.0
        self._total_blinks = 0
        self._minute: Optional[_Minute] = None
        # (t, distance_cm, pitch, yaw, luminance, face_px) while attending
        self._recent: Deque[Tuple[float, Optional[float], float, float, Optional[float],
                                  Optional[float]]] = deque()
        self.suggestions: Deque[Suggestion] = deque(maxlen=50)
        self.last_features: Optional[FrameFeatures] = None
        self.break_due: Optional[BreakDue] = None

    # ------------------------------------------------------------------ main
    def step(self, f: FrameFeatures) -> List[Any]:
        out: List[Any] = []
        t = f.t
        if self._t0 is None:
            self._t0 = t
        dt = 0.0 if self._last_t is None else min(max(t - self._last_t, 0.0), 1.0)
        self._last_t = t
        self.last_features = f

        attending = self.attention.attending(f.face, f.yaw)
        blink = self.detector.update(f)
        # Blink statistics only accrue while the eye signal is usable (not during warm-up,
        # steep head turns or hidden eyes), otherwise unseen blinks would deflate the rate.
        eyes_usable = self.detector.openness is not None
        if attending:
            self._screen_s += dt
            if eyes_usable:
                self.stats.add_observed(t, dt)
        if f.face:
            self._hidden.append((t, self.detector.eyes_hidden))
        while self._hidden and t - self._hidden[0][0] > 60:
            self._hidden.popleft()
        self.attention.update(t, dt, f.face, f.yaw, f.pitch)
        if blink is not None:
            out.extend(self._on_blink(blink))

        # Stare timer: time since the last blink while the eyes are continuously visible.
        # After any gap in usable eye data (away, turned, eyes hidden) we can't know when you
        # last blinked, so restart the timer rather than nag about an unseen stare.
        if f.face and (self._last_seen is None or t - self._last_seen > AWAY_RESET_S):
            self._last_blink_t = t
        if f.face and eyes_usable:
            self._last_seen = t
        stare = self.seconds_since_blink
        pending = self.detector.recent_min_openness(self.detector.p.after_s + 0.1)
        unconfirmed_dip = pending is not None and pending < 0.8
        if attending and eyes_usable and stare is not None and stare >= self.s.stare_seconds \
                and not unconfirmed_dip \
                and t - self._last_cue_t >= self.s.stare_seconds and self.s.blink_cue != "off":
            self._last_cue_t = t
            out.append(StareCue(stare))

        # Eyes closed for a while = resting, which counts toward breaks.
        o = self.detector.openness
        self._closed_run = self._closed_run + dt if (o is not None and o < REST_OPENNESS) else 0.0
        self._track_perclos(t, dt, o, attending)
        on_screen = attending and self._closed_run < 3.0

        low = self._low_blink()
        for ev in self.breaks.tick(t, dt, on_screen, low):
            out.append(ev)
            if isinstance(ev, BreakDue):
                self.break_due = ev
            elif isinstance(ev, BreakEnded):
                self.break_due = None

        self._track_recent(t, f, attending)
        self._track_activity(t, dt, f, attending)
        out.extend(self._roll_minute(t, dt, attending, stare, eyes_usable))

        if t - self._last_coach_t >= 10.0 and t - self._t0 >= 120.0:
            self._last_coach_t = t
            for sug in self.coach.evaluate(self._context(t)):
                self.suggestions.appendleft(sug)
                out.append(sug)
        return out

    def apply_settings(self) -> None:
        """Pick up changed settings (the Settings object is shared; schedulers copy values)."""
        b = self.breaks
        b.micro_s = self.s.micro_break_minutes * 60
        b.micro_len = self.s.micro_break_seconds
        b.long_s = self.s.long_break_minutes * 60
        b.long_len = self.s.long_break_seconds
        b.adaptive = self.s.adaptive_breaks

    def end_break(self, outcome: str) -> Optional[BreakEnded]:
        """UI callback when a break overlay finishes ('timer') or is skipped."""
        ev = self.breaks.finish(outcome)
        if ev is not None:
            self.break_due = None
        return ev

    # ------------------------------------------------------------ properties
    @property
    def seconds_since_blink(self) -> Optional[float]:
        if self._last_blink_t is None or self._last_t is None:
            return None
        return self._last_t - self._last_blink_t

    def snapshot(self) -> Dict[str, Any]:
        """Everything a UI needs, JSON-serialisable."""
        t = self._last_t or 0.0
        s1, s5, s10 = (self.stats.window(t, w) for w in (60, 300, 600))
        f = self.last_features
        dist, pitch, _, lum = self._medians(t)
        zones = self.attention.zones
        return {
            "t": t,
            "uptime_s": (t - self._t0) if self._t0 is not None else 0,
            "face": bool(f and f.face),
            "fps": round(self.detector.fps, 1),
            "openness": None if self.detector.openness is None else round(self.detector.openness, 3),
            "seconds_since_blink": None if self.seconds_since_blink is None
            else round(self.seconds_since_blink, 1),
            "blinks_total": self._total_blinks,
            "blink_rate_1m": _r(s1.rate), "blink_rate_5m": _r(s5.rate), "blink_rate_10m": _r(s10.rate),
            "incomplete_ratio_10m": _r(s10.incomplete_ratio, 3),
            "completeness_available": self.detector.fps >= self.detector.p.min_fps_for_completeness,
            "long_blinks_per_min_10m": _r(s10.long_per_min, 2),
            "perclos_5m": _r(s5.perclos, 3),
            "target_blink_rate": list(RELAXED_BLINK_RATE),
            "distance_cm": _r(dist, 0),
            "head_pitch": _r(pitch), "head_yaw": _r(f.yaw if f and f.face else None),
            "luminance": _r(lum, 0),
            "quality": self._quality_dict(),
            "people_in_view": f.faces if f is not None else 0,
            "head_pitch_now": _r(f.pitch if f and f.face else None),
            "face_px": _r(f.face_px if f and f.face else None, 0),
            "eyes_hidden": bool(self.detector.eyes_hidden),
            "eyes_visible": [_r(self.detector.vis_right, 3), _r(self.detector.vis_left, 3)],
            "screen_minutes": round(self._screen_s / 60, 1),
            "monitors_connected": self.monitors,
            "zones": [dict(index=z.index, yaw=round(z.center_yaw, 1), pitch=round(z.mean_pitch, 1),
                           share=round(z.share, 3), blink_rate=_r(z.blink_rate))
                      for z in zones],
            "current_zone": self.attention.current_zone,
            "switches_per_min": round(self.attention.switches_per_min(t), 2),
            "next_break_s": round(self.breaks.seconds_to_next(self._low_blink())),
            "break_active": None if self.breaks.active is None else self.breaks.active.kind,
            "breaks_completed": dict(self.breaks.completed),
            "breaks_missed": dict(self.breaks.missed),
            "suggestions": self._latest_suggestions(),
        }

    # ------------------------------------------------------------- internals
    def _quality_dict(self) -> Dict[str, Any]:
        q = self.quality()
        noise = self.detector.noise
        return {"level": q.level, "reasons": q.reasons, "tips": q.tips,
                "noise": None if noise is None else round(noise, 4)}

    def _latest_suggestions(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Most recent suggestion per rule, newest first (no repeats in the UI)."""
        seen, out = set(), []
        for s in self.suggestions:
            if s.rule in seen:
                continue
            seen.add(s.rule)
            out.append(dict(rule=s.rule, severity=s.severity, title=s.title,
                            message=s.message, refs=s.refs, t=s.t))
        return out[:limit]

    def _on_blink(self, b: Blink) -> List[Any]:
        self._total_blinks += 1
        self.stats.add_blink(b)
        self.attention.add_blink()
        self._last_blink_t = max(self._last_blink_t or b.end, b.end)
        self._stare20_counted = False
        if self._minute is not None:
            self._minute.blinks += 1
            if self._down_now:
                self._minute.blinks_down += 1
            if b.complete is not None:
                self._minute.judged += 1
                self._minute.incomplete += int(not b.complete)
            self._minute.long += int(b.long)
        return [BlinkEvent(b, self.attention.current_zone)]

    def _track_perclos(self, t: float, dt: float, o: Optional[float], attending: bool) -> None:
        if attending and o is not None and o <= PERCLOS_OPENNESS:
            self._p80_run += dt
            return
        # Eyes reopened (or tracking lost): count the closure unless it was a deliberate rest
        # or happened during a break.
        if 0 < self._p80_run <= PERCLOS_MAX_RUN_S and self.breaks.active is None:
            self.stats.add_closed(t, self._p80_run)
        self._p80_run = 0.0

    def _low_blink(self) -> bool:
        st = self.stats.window(self._last_t or 0.0, 600, min_observed_s=180)
        return st.rate is not None and st.rate < self.s.low_blink_rate

    def _track_recent(self, t: float, f: FrameFeatures, attending: bool) -> None:
        if attending:
            self._recent.append((t, f.distance_cm, f.pitch, f.yaw, f.luminance, f.face_px))
        while self._recent and t - self._recent[0][0] > 300:
            self._recent.popleft()

    def _medians(self, t: float):
        def med(idx: int, window: float) -> Optional[float]:
            vals = [r[idx] for r in self._recent if r[idx] is not None and t - r[0] <= window]
            return statistics.median(vals) if len(vals) >= 10 else None
        return med(1, 120), med(2, 300), med(3, 300), med(4, 120)

    def quality(self) -> Quality:
        t = self._last_t or 0.0
        vals = [r[5] for r in self._recent if r[5] is not None and t - r[0] <= 60]
        face_px = statistics.median(vals) if len(vals) >= 10 else None
        lum = self._medians(t)[3]
        hidden = (sum(h for _, h in self._hidden) / len(self._hidden)) if len(self._hidden) >= 10 else None
        return assess(self.detector.fps, face_px, lum, self.detector.noise, hidden)

    def _context(self, t: float) -> CoachContext:
        dist, pitch, _, lum = self._medians(t)
        return CoachContext(
            now=t, s1=self.stats.window(t, 60), s5=self.stats.window(t, 300),
            s10=self.stats.window(t, 600), distance_cm=dist, pitch=pitch, luminance=lum,
            zones=self.attention.zones, monitors=self.monitors,
            switches_per_min=self.attention.switches_per_min(t),
            screen_minutes=self._screen_s / 60.0, fps=self.detector.fps, quality=self.quality())

    def screen_pitch(self) -> float:
        """Your usual head pitch when looking at your screens (time-weighted over zones)."""
        zones = self.attention.zones
        if not zones:
            return -5.0
        return sum(z.mean_pitch * z.share for z in zones) / max(sum(z.share for z in zones), 1e-9)

    def _track_activity(self, t: float, dt: float, f: FrameFeatures, attending: bool) -> None:
        # Continuous use: resets only after a real break (2+ min away).
        if attending:
            self._continuous_s += dt
            self._away_run = 0.0
        else:
            self._away_run += dt
            if self._away_run >= CONTINUOUS_RESET_S:
                self._continuous_s = 0.0
        # Looking down at another device: well below your screen, sustained for 1 s.
        below = f.face and f.pitch < self.screen_pitch() - DOWN_DEG
        if below:
            self._down_since = self._down_since if self._down_since is not None else t
        else:
            self._down_since = None
        down = self._down_since is not None and t - self._down_since >= 1.0
        m = self._minute
        if m is not None:
            if down:
                m.down_s += dt
                if self.detector.openness is not None:
                    m.obs_down_s += dt
            if down != self._down_now and (down or self._down_now):
                m.device_switches += 1
        self._down_now = down
        stare = self.seconds_since_blink
        if stare is not None and stare >= 20 and not self._stare20_counted and attending:
            self._stare20_counted = True
            if m is not None:
                m.stares20 += 1

    def _roll_minute(self, t: float, dt: float, attending: bool,
                     stare: Optional[float], eyes_usable: bool = True) -> List[MinuteSummary]:
        m = self._minute
        if m is None:
            self._minute = _Minute(start=t, session_min=self._continuous_s / 60)
            return []
        if attending and eyes_usable:
            m.observed += dt
            if stare is not None:
                m.max_stare = max(m.max_stare, stare)
        if t - m.start < 60.0:
            return []
        dist, pitch, yaw, lum = self._medians(t)
        summary = MinuteSummary(
            t=m.start, observed_s=round(m.observed, 1), blinks=m.blinks, judged=m.judged,
            incomplete=m.incomplete, long=m.long, max_stare_s=round(m.max_stare, 1),
            distance_cm=dist, pitch=pitch, yaw=yaw, luminance=lum,
            zones=len(self.attention.zones),
            switches_per_min=round(self.attention.switches_per_min(t), 2),
            session_min=round(m.session_min, 1), down_s=round(m.down_s, 1),
            obs_down_s=round(m.obs_down_s, 1), blinks_down=m.blinks_down,
            device_switches=m.device_switches, stares20=m.stares20)
        self._minute = _Minute(start=t, session_min=self._continuous_s / 60)
        return [summary]


def _r(v: Optional[float], nd: int = 1) -> Optional[float]:
    return None if v is None else round(v, nd)

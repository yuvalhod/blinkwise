"""Turns measurements into a few well-timed, evidence-backed suggestions.

Design rules (notification fatigue kills habits):
  * Every rule has its own cooldown, and there is a global minimum gap
    between notifications. Everything stays visible on the dashboard
    regardless.
  * Each message says what we measured, why it matters, and one thing to do,
    with references (research.REFERENCES).
  * Rules need enough observed data before they fire; nothing is said in the
    first couple of minutes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ..config import Settings
from ..vision.attention import Zone
from ..vision.quality import Quality
from .events import Suggestion
from .metrics import WindowStats

SEVERITY_RANK = {"info": 0, "warn": 1, "high": 2}
BLINK_RULES = {"low_blink_rate", "incomplete_blinks", "fatigue", "screen_zone_blink_gap"}


@dataclass
class CoachContext:
    now: float
    s1: WindowStats
    s5: WindowStats
    s10: WindowStats
    distance_cm: Optional[float]     # median over the last ~2 min
    pitch: Optional[float]           # median head pitch over the last ~5 min
    luminance: Optional[float]
    zones: List[Zone]
    monitors: Optional[int]
    switches_per_min: float
    screen_minutes: float            # total attended minutes this session
    fps: float
    quality: Quality = field(default_factory=lambda: Quality("unknown"))


@dataclass
class _Rule:
    name: str
    cooldown_s: float
    fn: Callable[[CoachContext, Settings], Optional[Suggestion]]


@dataclass
class Coach:
    settings: Settings
    _last_fired: Dict[str, float] = field(default_factory=dict)
    _last_notify: float = -1e9
    _rules: List[_Rule] = field(default_factory=list)

    def __post_init__(self):
        self._rules = [
            _Rule("low_blink_rate", 15 * 60, rule_low_blink_rate),
            _Rule("incomplete_blinks", 45 * 60, rule_incomplete_blinks),
            _Rule("fatigue", 30 * 60, rule_fatigue),
            _Rule("too_close", 30 * 60, rule_too_close),
            _Rule("screen_too_high", 60 * 60, rule_screen_too_high),
            _Rule("multi_screen", 60 * 60, rule_multi_screen),
            _Rule("screen_zone_blink_gap", 60 * 60, rule_zone_blink_gap),
            _Rule("dim_light", 60 * 60, rule_dim_light),
            _Rule("young_outdoors", 4 * 3600, rule_young_outdoors),
            _Rule("tracking_quality", 30 * 60, rule_tracking_quality),
        ]

    def evaluate(self, ctx: CoachContext) -> List[Suggestion]:
        fired: List[Suggestion] = []
        for r in self._rules:
            last = self._last_fired.get(r.name, -1e9)
            if ctx.now - last < r.cooldown_s:
                continue
            if r.name in BLINK_RULES and ctx.quality.level == "poor":
                continue        # don't give blink advice from unreliable measurements
            s = r.fn(ctx, self.settings)
            if s is None:
                continue
            s.rule, s.t = r.name, ctx.now
            self._last_fired[r.name] = ctx.now
            fired.append(s)
        # At most one notification, the most severe, and not too often.
        fired.sort(key=lambda s: -SEVERITY_RANK[s.severity])
        if fired and ctx.now - self._last_notify >= self.settings.min_notification_gap_s:
            top = fired[0]
            if top.severity != "info" or ctx.screen_minutes >= 10:
                top.notify = True
                self._last_notify = ctx.now
        return fired


# ---------------------------------------------------------------------------
# Rules. Each returns a Suggestion or None. Keep them small and testable.
# ---------------------------------------------------------------------------

def rule_low_blink_rate(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    st = c.s5
    if st.rate is None or st.observed_s < 180:
        return None
    if st.rate >= s.low_blink_rate:
        return None
    sev = "high" if st.rate < s.very_low_blink_rate else "warn"
    return Suggestion(
        "", sev, f"You're blinking {st.rate:.0f}x per minute",
        f"Over the last 5 minutes you blinked about {st.rate:.0f} times a minute. Relaxed eyes "
        "blink roughly 15-20 times a minute; screens commonly cut that to a third or less, "
        "which lets the tear film dry out. Try a few slow, full blinks now - lids all the way "
        "closed.",
        refs=["patel1991", "tsubota1993"], data={"rate": round(st.rate, 1)})


def rule_incomplete_blinks(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    st = c.s10
    if st.incomplete_ratio is None or st.incomplete_ratio < 0.4:
        return None
    pct = round(st.incomplete_ratio * 100)
    return Suggestion(
        "", "warn", f"{pct}% of your blinks are partial",
        f"About {pct}% of your recent blinks didn't fully close. Eye-strain symptoms track the "
        "share of incomplete blinks more closely than blink rate. A blinking exercise helps "
        "retrain full closure: close gently (2 s), squeeze gently (2 s), open - repeat 10 "
        "times, a few times a day.",
        refs=["portello2013", "kim2020", "aston2025"], data={"incomplete_pct": pct})


def rule_fatigue(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    """PERCLOS (share of time with eyes >= 80% closed) is the best-validated camera
    measure of drowsiness; ~15% over a few minutes is a commonly used alert level."""
    p5 = c.s5.perclos
    if p5 is not None and c.s5.observed_s >= 180 and p5 >= 0.15:
        return Suggestion(
            "", "high", "You look drowsy",
            f"Your eyes have been mostly closed {p5 * 100:.0f}% of the time over the last 5 "
            "minutes. That's a validated sign of drowsiness, and attention suffers long before "
            "you notice it. Take a proper break: stand up, get daylight or fresh air, or rest.",
            refs=["dinges1998"], data={"perclos": round(p5, 3)})
    st = c.s10
    if st.long_per_min is None or st.observed_s < 300 or st.long_per_min < 1.5:
        return None
    return Suggestion(
        "", "warn", "Your eyes look tired",
        f"You're having frequent long eye closures ({st.long_per_min:.1f} per minute), a common "
        "sign of fatigue. Consider a proper break away from screens.",
        refs=["sheppard2018", "dinges1998"], data={"long_per_min": round(st.long_per_min, 2)})


def rule_too_close(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    d = c.distance_cm
    if d is None or d >= s.min_distance_cm:
        return None
    return Suggestion(
        "", "warn", f"You're about {d:.0f} cm from the screen",
        f"Your eyes are roughly {d:.0f} cm from the camera. 50-70 cm (about an arm's length) "
        "is recommended, which also reduces focusing effort. Lean back or push the screen "
        "away and increase text size if needed.",
        refs=["aoa_ergonomics"], data={"distance_cm": round(d)})


def rule_screen_too_high(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    # With the camera on top of the main screen, looking at the screen centre means a slightly
    # downward head pitch. A sustained upward pitch suggests the screen sits too high,
    # which exposes more of the eye's surface and dries it faster.
    if c.pitch is None or s.camera_position != "top" or c.pitch < 8.0:
        return None
    return Suggestion(
        "", "info", "Your screen may be too high",
        "You're tilting your head up to look at the screen. A lower gaze narrows the "
        "eye opening and slows tear evaporation. Put the centre of the screen about 15-20 "
        "degrees below eye level (the top edge at or slightly below eye height).",
        refs=["tsubota1995", "aoa_ergonomics"], data={"pitch": round(c.pitch, 1)})


def rule_multi_screen(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    zones = c.zones
    if len(zones) < 2 or c.screen_minutes < 10:
        return None
    main = max(zones, key=lambda z: z.share)
    far = max(zones, key=lambda z: abs(z.center_yaw))
    split = " / ".join(f"{z.share * 100:.0f}%" for z in zones)
    parts = [f"You're actively using {len(zones)} screens (time split {split}) and switching "
             f"between them about {c.switches_per_min:.1f} times a minute."]
    if c.monitors and c.monitors > len(zones):
        parts.append(f"({c.monitors} displays are connected.)")
    if abs(main.center_yaw) > 15:
        parts.append(f"Your most-used screen sits about {abs(main.center_yaw):.0f} degrees to "
                     "the side. Put the screen you use most directly in front of you.")
    if abs(far.center_yaw) > 35:
        parts.append(f"One screen needs a {abs(far.center_yaw):.0f} degree head turn. Angle it "
                     "inward or move it closer to cut neck strain and eye exposure.")
    parts.append("Keep all screens at the same height and distance so your eyes don't refocus "
                 "on every switch.")
    sev = "warn" if abs(far.center_yaw) > 35 or abs(main.center_yaw) > 15 else "info"
    return Suggestion("", sev, f"{len(zones)}-screen setup detected", " ".join(parts),
                      refs=["aoa_ergonomics"],
                      data={"zones": len(zones), "split": [round(z.share, 2) for z in zones],
                            "yaws": [round(z.center_yaw) for z in zones]})


def rule_zone_blink_gap(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    rated = [z for z in c.zones if z.blink_rate is not None and z.observed_s >= 300]
    if len(rated) < 2:
        return None
    lo = min(rated, key=lambda z: z.blink_rate)
    hi = max(rated, key=lambda z: z.blink_rate)
    if hi.blink_rate <= 0 or lo.blink_rate / hi.blink_rate > 0.6:
        return None
    # Only claim a difference that is statistically solid (Poisson rate comparison).
    k_lo, k_hi = lo.blink_rate * lo.observed_s / 60, hi.blink_rate * hi.observed_s / 60
    if poisson_rate_p_value(k_lo, lo.observed_s, k_hi, hi.observed_s) > 0.01:
        return None
    side = "left" if lo.center_yaw < hi.center_yaw else "right"
    drop = round((1 - lo.blink_rate / hi.blink_rate) * 100)
    return Suggestion(
        "", "info", f"You blink {drop}% less on your {side} screen",
        f"On your {side} screen you blink about {lo.blink_rate:.0f}/min, against "
        f"{hi.blink_rate:.0f}/min on the other. Demanding content (code, games, spreadsheets) "
        "suppresses blinking. Be deliberate about blinking when you work there.",
        refs=["patel1991"], data={"low": round(lo.blink_rate, 1), "high": round(hi.blink_rate, 1)})


def poisson_rate_p_value(k1: float, e1: float, k2: float, e2: float) -> float:
    """Two-sided p-value that two Poisson rates (counts k over exposures e) are equal.

    Conditional test: given n = k1 + k2, k1 ~ Binomial(n, e1 / (e1 + e2)) under H0.
    Normal approximation with continuity correction (fine for n >= ~20; we
    return 1.0 below that so we never claim a difference on thin data).
    """
    n = k1 + k2
    if n < 20 or e1 <= 0 or e2 <= 0:
        return 1.0
    p = e1 / (e1 + e2)
    sd = math.sqrt(n * p * (1 - p))
    z = (abs(k1 - n * p) - 0.5) / sd
    return math.erfc(max(z, 0.0) / math.sqrt(2))


def rule_dim_light(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    if c.luminance is None or c.luminance >= 45:
        return None
    return Suggestion(
        "", "info", "Your room looks dark",
        "Your face is dimly lit, so the screen is probably much brighter than the room. "
        "Turn on some ambient light or lower the screen brightness to reduce glare and "
        "strain.",
        refs=["sheppard2018"], data={"luminance": round(c.luminance)})


def rule_young_outdoors(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    if s.profile != "young" or c.screen_minutes < 60:
        return None
    return Suggestion(
        "", "info", "Get some daylight today",
        "For children and teens, time outdoors in daylight is one of the best-supported ways "
        "to slow the onset of short-sightedness. In one trial, an extra 40 minutes outside "
        "each school day cut new myopia cases. Aim for 1-2 hours outdoors a day.",
        refs=["he2015"])


def rule_tracking_quality(c: CoachContext, s: Settings) -> Optional[Suggestion]:
    q = c.quality
    if q.level != "poor" or c.screen_minutes < 2:
        return None
    return Suggestion(
        "", "warn", "Blinkwise can't see your eyes clearly",
        f"Tracking is unreliable right now ({'; '.join(q.reasons)}), so blink-based advice is "
        f"paused rather than risk being wrong. {' '.join(q.tips)}",
        refs=[], data={"reasons": q.reasons})

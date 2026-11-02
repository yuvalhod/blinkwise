"""Personal patterns from per-minute history.

Everything here is a pure function of minute rows (dicts from
History.minute_rows), so it's tested with synthetic data and never touches the
camera. Each analysis says when it has too little data instead of guessing.

  * blink decay     how your blink rate falls with continuous use, and the point
                    where it drops 20% below your fresh-start rate -> a break
                    interval fitted to you
  * time of day     blink rate by hour
  * devices         time looking down at a phone/tablet/paper, how often you
                    switch, and blink rate there vs. on screen
  * stares          20 s+ stares per hour of screen time
  * posture drift   whether you lean in (get closer) as the day goes on
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Row = Dict[str, Any]

SESSION_BINS = [(0, 10), (10, 20), (20, 30), (30, 45), (45, 60), (60, 90), (90, 10_000)]
MIN_BIN_OBS_MIN = 15.0      # observed minutes needed before a bin is shown
DECAY_DROP = 0.2            # "fatigued" = 20% below your fresh rate


@dataclass
class Insight:
    key: str
    title: str
    detail: str
    data: Dict[str, Any] = field(default_factory=dict)


def _rate(blinks: float, obs_s: float) -> Optional[float]:
    return blinks / obs_s * 60.0 if obs_s >= MIN_BIN_OBS_MIN * 60 else None


def blink_decay(rows: List[Row]) -> Dict[str, Any]:
    """Blink rate by minutes of continuous use (since the last 2+ minute break)."""
    bins = []
    for lo, hi in SESSION_BINS:
        sel = [r for r in rows if lo <= (r.get("session_min") or 0) < hi]
        obs = sum(r["observed_s"] for r in sel)
        bl = sum(r["blinks"] for r in sel)
        bins.append({"from": lo, "to": hi if hi < 10_000 else None,
                     "observed_min": round(obs / 60, 1), "rate": _r(_rate(bl, obs))})
    fresh = bins[0]["rate"]
    fatigue_at = None
    if fresh:
        for b in bins[1:]:
            if b["rate"] is not None and b["rate"] <= fresh * (1 - DECAY_DROP):
                fatigue_at = b["from"]
                break
    return {"bins": bins, "fresh_rate": fresh, "fatigue_after_min": fatigue_at}


def by_hour(rows: List[Row]) -> List[Dict[str, Any]]:
    acc = defaultdict(lambda: [0.0, 0])
    for r in rows:
        h = time.localtime(r["ts"]).tm_hour
        acc[h][0] += r["observed_s"]
        acc[h][1] += r["blinks"]
    return [{"hour": h, "observed_min": round(o / 60, 1), "rate": _r(_rate(b, o))}
            for h, (o, b) in sorted(acc.items())]


def devices(rows: List[Row]) -> Dict[str, Any]:
    screen_s = sum(max(0.0, r["observed_s"] - (r.get("obs_down_s") or 0)) for r in rows)
    down_s = sum(r.get("down_s") or 0 for r in rows)
    obs_down = sum(r.get("obs_down_s") or 0 for r in rows)
    blinks_down = sum(r.get("blinks_down") or 0 for r in rows)
    blinks_screen = sum(r["blinks"] for r in rows) - blinks_down
    attended_s = sum(r["observed_s"] for r in rows) + max(0.0, down_s - obs_down)
    switches = sum(r.get("device_switches") or 0 for r in rows)
    hours = attended_s / 3600
    return {
        "down_share": round(down_s / attended_s, 3) if attended_s else None,
        "down_minutes": round(down_s / 60, 1),
        "switches_per_hour": round(switches / hours, 1) if hours >= 0.5 else None,
        "rate_screen": _r(_rate(blinks_screen, screen_s)),
        "rate_down": _r(blinks_down / obs_down * 60) if obs_down >= 5 * 60 else None,
    }


def stares(rows: List[Row]) -> Optional[float]:
    obs = sum(r["observed_s"] for r in rows)
    if obs < 30 * 60:
        return None
    return round(sum(r.get("stares20") or 0 for r in rows) / (obs / 3600), 1)


def posture_drift(rows: List[Row]) -> Optional[Dict[str, float]]:
    """Median distance in the first vs. last third of each day's screen time."""
    by_day = defaultdict(list)
    for r in rows:
        if r.get("distance_cm"):
            by_day[time.strftime("%Y-%m-%d", time.localtime(r["ts"]))].append(r["distance_cm"])
    early, late = [], []
    for vals in by_day.values():
        if len(vals) < 60:
            continue
        k = len(vals) // 3
        early += vals[:k]
        late += vals[-k:]
    if len(early) < 60:
        return None
    return {"early_cm": round(statistics.median(early)), "late_cm": round(statistics.median(late))}


def insights(rows: List[Row]) -> List[Insight]:
    out: List[Insight] = []
    d = blink_decay(rows)
    if d["fatigue_after_min"] is not None:
        later = next(b for b in d["bins"] if b["from"] == d["fatigue_after_min"])
        drop = round((1 - later["rate"] / d["fresh_rate"]) * 100)
        out.append(Insight(
            "decay", f"Your blinking drops {drop}% after about {d['fatigue_after_min']} minutes",
            f"Fresh from a break you blink about {d['fresh_rate']:.0f} times a minute; after "
            f"{d['fatigue_after_min']} minutes of continuous screen time it's about "
            f"{later['rate']:.0f}. Breaks just before that point help most.",
            {"suggested_break_min": max(10, min(60, d["fatigue_after_min"]))}))
    dv = devices(rows)
    if dv["down_share"] is not None and dv["down_share"] >= 0.05:
        detail = (f"You spent about {dv['down_share'] * 100:.0f}% of your screen time looking down "
                  "at another device or paper")
        if dv["switches_per_hour"]:
            detail += f", switching about {dv['switches_per_hour']:.0f} times an hour"
        detail += ". Each switch makes your eyes refocus to a new distance."
        if dv["rate_down"] is not None and dv["rate_screen"]:
            detail += (f" You blink about {dv['rate_down']:.0f}/min there vs "
                       f"{dv['rate_screen']:.0f}/min on screen.")
        out.append(Insight("devices", "You use more than one device at once", detail, dv))
    hours = [h for h in by_hour(rows) if h["rate"] is not None]
    if len(hours) >= 4:
        lo = min(hours, key=lambda h: h["rate"])
        hi = max(hours, key=lambda h: h["rate"])
        if hi["rate"] and lo["rate"] <= 0.75 * hi["rate"]:
            out.append(Insight(
                "hour", f"You blink least around {lo['hour']}:00",
                f"About {lo['rate']:.0f}/min at {lo['hour']}:00 vs {hi['rate']:.0f}/min at "
                f"{hi['hour']}:00. Plan a real break around then.", {"low_hour": lo["hour"]}))
    st = stares(rows)
    if st is not None and st >= 6:
        out.append(Insight("stares", f"{st:.0f} long stares an hour",
                           f"About {st:.0f} times an hour you go 20 seconds or more without "
                           "blinking, usually during intense focus.", {"per_hour": st}))
    pd = posture_drift(rows)
    if pd and pd["early_cm"] - pd["late_cm"] >= 5:
        out.append(Insight("posture", "You lean in as the day goes on",
                           f"You sit about {pd['early_cm']} cm from the screen early in the day and "
                           f"{pd['late_cm']} cm later on. Leaning closer usually means fatigue or "
                           "small text.", pd))
    return out


def report(rows: List[Row]) -> Dict[str, Any]:
    obs_h = sum(r["observed_s"] for r in rows) / 3600
    return {
        "hours_of_data": round(obs_h, 1),
        "decay": blink_decay(rows),
        "by_hour": by_hour(rows),
        "devices": devices(rows),
        "stares_per_hour": stares(rows),
        "posture": posture_drift(rows),
        "insights": [i.__dict__ for i in insights(rows)],
    }


def _r(v: Optional[float], nd: int = 1) -> Optional[float]:
    return None if v is None else round(v, nd)

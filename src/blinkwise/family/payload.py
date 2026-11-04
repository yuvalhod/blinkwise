"""The only data that leaves a child's computer: weekly totals.

The child's app builds this from its local history and shows it, word for word,
under "What's shared" before and while sharing is on. The server accepts exactly
these fields and ranges and rejects anything else.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

VERSION = 1

# field -> (type, min, max, label for people)
FIELDS = {
    "week_start": (str, None, None, "Week starting"),
    "days_active": (int, 0, 7, "Days with screen time"),
    "screen_per_day": (int, 0, 1440, "Screen time a day (min)"),
    "phone_per_day": (int, 0, 1440, "Phone time a day (min)"),
    "blink_rate": (float, 0, 60, "Blinks a minute"),
    "full_blinks": (int, 0, 100, "Full blinks (%)"),
    "breaks_pct": (int, 0, 100, "Eye breaks taken (%)"),
    "breaks_taken": (int, 0, 2000, "Eye breaks taken"),
    "distance_cm": (int, 10, 300, "Viewing distance (cm)"),
    "posture_per_day": (int, 0, 1440, "Strained posture a day (min)"),
    "checkin_total": (int, 0, 9, "Eye check-in score (0 best, 9 worst)"),
}


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())          # Monday


def build(days: Sequence[Dict[str, Any]], checkins: Sequence[Dict[str, Any]],
          start: date, share_checkin: bool = False) -> Optional[Dict[str, Any]]:
    """Totals for the Monday-Sunday week beginning `start`. None if there's no data."""
    from ..core.weekly import _week, total
    end = start + timedelta(days=6)
    w = _week(days, start, end)
    if not w["days"]:
        return None
    out: Dict[str, Any] = {"v": VERSION, "week_start": start.isoformat(), "days_active": w["days"]}
    for k in ("screen_per_day", "phone_per_day", "blink_rate", "full_blinks", "breaks_pct",
              "breaks_taken", "distance_cm", "posture_per_day"):
        if w.get(k) is not None:
            out[k] = w[k]
    if share_checkin:
        lo = datetime.combine(start, datetime.min.time()).timestamp()
        hi = lo + 7 * 86400
        inside = [c for c in checkins if lo <= c["ts"] < hi]
        if inside:
            out["checkin_total"] = total(inside[-1])
    return out


def recent(days, checkins, today: date, share_checkin: bool = False) -> List[Dict[str, Any]]:
    """Last week (final) and this week so far."""
    this = week_start(today)
    out = []
    for start in (this - timedelta(days=7), this):
        p = build(days, checkins, start, share_checkin)
        if p is not None:
            out.append(p)
    return out


def validate(p: Any) -> Dict[str, Any]:
    """Server side: exact schema, sane ranges. Raises ValueError."""
    if not isinstance(p, dict) or p.get("v") != VERSION:
        raise ValueError("unsupported payload")
    extra = set(p) - set(FIELDS) - {"v"}
    if extra:
        raise ValueError(f"unexpected fields: {sorted(extra)}")
    out: Dict[str, Any] = {"v": VERSION}
    for k, (typ, lo, hi, _) in FIELDS.items():
        if k not in p or p[k] is None:
            continue
        v = p[k]
        if typ is str:
            d = date.fromisoformat(str(v))
            if d.weekday() != 0:
                raise ValueError("week_start must be a Monday")
            out[k] = d.isoformat()
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{k} must be a number")
        if not lo <= v <= hi:
            raise ValueError(f"{k} out of range")
        out[k] = typ(v) if typ is int else round(float(v), 1)
    if "week_start" not in out:
        raise ValueError("week_start is required")
    return out


def describe(p: Dict[str, Any]) -> List[List[str]]:
    """[[label, value], ...] for showing a payload to people."""
    rows = []
    for k, (_, _, _, label) in FIELDS.items():
        if k in p:
            rows.append([label, str(p[k])])
    return rows

"""The end-of-day summary: one short, honest notification.

Compares today with your own recent days (not a generic norm), names one thing
that went well and one to try tomorrow. Silent on light days.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

MIN_SCREEN_MINUTES = 30


def _hm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def build(days: List[Dict[str, Any]], today: Optional[str] = None,
          insights: Optional[List[Dict[str, Any]]] = None) -> Optional[Tuple[str, str]]:
    """days: History.daily() rows (oldest first). Returns (title, message) or None."""
    today = today or time.strftime("%Y-%m-%d")
    cur = next((d for d in days if d["day"] == today), None)
    if cur is None or (cur.get("screen_minutes") or 0) < MIN_SCREEN_MINUTES:
        return None
    past = [d for d in days if d["day"] != today and d.get("blink_rate")][-7:]
    rate = cur.get("blink_rate")
    taken, missed = cur.get("breaks_taken", 0), cur.get("breaks_missed", 0)
    parts = [f"{_hm(cur['screen_minutes'])} on screen"]
    good, todo = None, None
    if rate is not None:
        txt = f"blinked {rate:.0f}/min"
        if past:
            avg = sum(d["blink_rate"] for d in past) / len(past)
            if rate >= avg * 1.1:
                good = f"you blinked more than your recent average ({avg:.0f}/min)"
            elif rate <= avg * 0.9:
                todo = "you blinked less than usual - try a few deliberate full blinks each hour"
            txt += f" (recent average {avg:.0f})"
        parts.append(txt)
    if taken + missed:
        parts.append(f"{taken} of {taken + missed} breaks")
        if taken / (taken + missed) >= 0.75 and good is None:
            good = "you took most of your breaks"
        elif taken / (taken + missed) < 0.5 and todo is None:
            todo = "you skipped most breaks - even 20 seconds of looking far away helps"
    if todo is None and insights:
        dec = next((i for i in insights if i.get("key") == "decay"), None)
        if dec:
            todo = f"your blinking drops after ~{dec['data']['suggested_break_min']} min; break before then"
    msg = ", ".join(parts) + "."
    if good:
        msg += f" Nice: {good}."
    if todo:
        msg += f" Tomorrow: {todo}."
    return "Your eyes today", msg


def due(setting: str, last_sent_day: Optional[str], now: Optional[float] = None) -> bool:
    """True when the configured local time has passed and today's summary wasn't sent."""
    if not setting:
        return False
    lt = time.localtime(now or time.time())
    try:
        h, m = (int(x) for x in setting.split(":"))
    except ValueError:
        return False
    today = time.strftime("%Y-%m-%d", lt)
    return last_sent_day != today and (lt.tm_hour, lt.tm_min) >= (h, m)

"""Weekly eye check-in and weekly report. View-only: nothing is sent anywhere.

Check-in
  Three questions about the past week, answered Never / Sometimes / Often / Almost always
  (0-3). They cover the three symptom groups that screen-related eye-strain
  questionnaires keep coming back to: surface dryness/irritation, tired/strained eyes,
  and blurred vision. The wording is our own (inspired by OSDI and CVS-Q, not a
  validated instrument), so the score is a personal trend, not a diagnosis.

  We suggest seeing an eye-care professional when a symptom is there "almost always",
  or the total stays high (>= 6 of 9) for two check-ins in a row: persistent symptoms
  can have causes a habit app can't fix (dry eye disease, uncorrected vision, ...).

Report
  This week vs last week: screen time, phone time, blink rate, full blinks, breaks
  taken, viewing distance. One gentle goal, picked from what most needs attention.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

QUESTIONS = (
    ("dry", "Dry, gritty or burning eyes"),
    ("tired", "Tired or strained eyes"),
    ("blurry", "Blurry vision after screen use"),
)
ANSWERS = ("Never", "Sometimes", "Often", "Almost always")
CHECKIN_EVERY_DAYS = 7
MIN_DAYS_USED = 3          # don't ask before Blinkwise has seen a few days
HIGH_TOTAL = 6


def checkin_due(checkins: Sequence[Dict[str, Any]], days_used: int,
                now: Optional[float] = None) -> bool:
    now = now or time.time()
    if checkins:
        return now - checkins[-1]["ts"] >= CHECKIN_EVERY_DAYS * 86400 - 3600
    return days_used >= MIN_DAYS_USED


def total(c: Dict[str, Any]) -> int:
    return sum(int(c[k]) for k, _ in QUESTIONS)


def checkin_advice(checkins: Sequence[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not checkins:
        return None
    last = checkins[-1]
    t = total(last)
    prev = checkins[-2] if len(checkins) >= 2 else None
    worst = max(QUESTIONS, key=lambda q: last[q[0]])
    if last[worst[0]] >= 3 or (t >= HIGH_TOTAL and prev is not None and total(prev) >= HIGH_TOTAL):
        return {"level": "doctor",
                "title": "Worth seeing an eye-care professional",
                "text": ("Your eyes have bothered you a lot" +
                         (" for two weeks running" if prev is not None and total(prev) >= HIGH_TOTAL
                          else "") +
                         ". An optometrist or ophthalmologist can check for dry eye or a "
                         "prescription change. Blinkwise is a habit tool, not a diagnosis.")}
    if t >= HIGH_TOTAL:
        return {"level": "watch", "title": "Your eyes had a rough week",
                "text": "Take every break this week and blink fully. We'll ask again in 7 days."}
    if prev is not None and t < total(prev):
        return {"level": "good", "title": "Better than last week", "text": "Keep the habits going."}
    return {"level": "good", "title": "Thanks", "text": "We'll ask again in a week."}


# ------------------------------------------------------------------- report
def _week(days: Sequence[Dict[str, Any]], start: date, end: date) -> Dict[str, Any]:
    rows = [d for d in days if start <= date.fromisoformat(d["day"]) <= end]
    active = [d for d in rows if (d.get("screen_minutes") or 0) + (d.get("device_minutes") or 0) >= 10]
    n = len(active)
    obs = sum(d.get("observed_minutes") or 0 for d in rows)
    blinks = sum(d.get("blinks") or 0 for d in rows)
    taken = sum(d.get("breaks_taken") or 0 for d in rows)
    missed = sum(d.get("breaks_missed") or 0 for d in rows)
    inc = [(d["incomplete_ratio"], d.get("blinks") or 0) for d in rows
           if d.get("incomplete_ratio") is not None]
    dist = [d["distance_cm"] for d in rows if d.get("distance_cm")]
    return {
        "days": n,
        "screen_per_day": round(sum(d.get("screen_minutes") or 0 for d in active) / n) if n else None,
        "phone_per_day": round(sum(d.get("device_minutes") or 0 for d in active) / n) if n else None,
        "blink_rate": round(blinks / obs, 1) if obs >= 30 else None,
        "full_blinks": (round(100 * (1 - sum(r * w for r, w in inc) / sum(w for _, w in inc)))
                        if inc and sum(w for _, w in inc) else None),
        "breaks_pct": round(100 * taken / (taken + missed)) if taken + missed >= 3 else None,
        "breaks_taken": taken,
        "distance_cm": round(sorted(dist)[len(dist) // 2]) if dist else None,
        "posture_per_day": (round(sum(d.get("posture_minutes") or 0 for d in active) / n)
                            if n and any("posture_minutes" in d for d in active) else None),
    }


def pick_goal(this: Dict[str, Any], symptoms: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """One goal, the most useful first. Gentle, concrete, checkable next week."""
    rate, br, full = this.get("blink_rate"), this.get("breaks_pct"), this.get("full_blinks")
    dist = this.get("distance_cm")
    dry = bool(symptoms and symptoms.get("dry", 0) >= 2)
    if rate is not None and (rate < 10 or (dry and rate < 15)):
        target = int(min(15, max(rate + 2, 10)))
        return {"key": "blink_rate", "target": str(target),
                "text": f"Average {target} blinks a minute. When the eye cue appears, "
                        "close your eyes fully for a moment."}
    if br is not None and br < 60:
        return {"key": "breaks_pct", "target": "70",
                "text": "Take 7 of every 10 eye breaks. They're 20 seconds: look out a window."}
    if full is not None and full < 60:
        return {"key": "full_blinks", "target": "70",
                "text": "Make 7 in 10 blinks full ones: a few times an hour, close gently, pause, open."}
    if dist is not None and dist < 50:
        return {"key": "distance_cm", "target": "50",
                "text": "Sit back to about an arm's length (50 cm or more) from your screen."}
    posture = this.get("posture_per_day")
    if posture is not None and posture >= 45:
        return {"key": "posture_per_day", "target": str(int(posture * 0.6)),
                "text": "Sit back and tall: when Blinkwise says you're leaning in or your chin "
                        "is down, reset and roll your shoulders."}
    phone = this.get("phone_per_day")
    if phone is not None and phone >= 90:
        return {"key": "phone_per_day", "target": str(int(phone * 0.8)),
                "text": f"Bring phone time down to about {int(phone * 0.8)} min a day."}
    return {"key": "keep", "target": "", "text": "You're doing well. Keep this week's habits."}


def _arrow(this, last, higher_is_better: bool) -> Optional[str]:
    if this is None or last is None or this == last:
        return None
    better = (this > last) == higher_is_better
    return "better" if better else "worse"


def report(days: Sequence[Dict[str, Any]], checkins: Sequence[Dict[str, Any]] = (),
           today: Optional[date] = None) -> Dict[str, Any]:
    today = today or datetime.now().date()
    this = _week(days, today - timedelta(days=6), today)
    last = _week(days, today - timedelta(days=13), today - timedelta(days=7))
    rows: List[Dict[str, Any]] = []
    for key, label, unit, better_high in (
            ("screen_per_day", "Screen time a day", "min", False),
            ("phone_per_day", "Phone time a day", "min", False),
            ("blink_rate", "Blinks a minute", "/min", True),
            ("full_blinks", "Full blinks", "%", True),
            ("breaks_pct", "Eye breaks taken", "%", True),
            ("distance_cm", "Viewing distance", "cm", True),
            ("posture_per_day", "Strained posture a day", "min", False)):
        if this.get(key) is None and last.get(key) is None:
            continue
        rows.append({"key": key, "label": label, "unit": unit, "this": this.get(key),
                     "last": last.get(key), "trend": _arrow(this.get(key), last.get(key), better_high)})
    recent = [c for c in checkins if c["ts"] >= time.mktime((today - timedelta(days=13)).timetuple())]
    last_goal = pick_goal(last) if last["days"] else None
    goal_met = None
    if last_goal and last_goal["key"] not in ("keep",) and this.get(last_goal["key"]) is not None:
        v, tgt = this[last_goal["key"]], float(last_goal["target"])
        goal_met = v <= tgt if last_goal["key"] in ("phone_per_day", "posture_per_day") else v >= tgt
    return {
        "has_data": this["days"] > 0,
        "days_this_week": this["days"],
        "rows": rows,
        "goal": pick_goal(this, checkins[-1] if checkins else None),
        "last_goal": last_goal, "last_goal_met": goal_met,
        "checkins": [{"ts": c["ts"], "total": total(c)} for c in recent],
    }

"""Local history in SQLite: per-minute aggregates only. No images, ever."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .events import BreakEnded, MinuteSummary, Suggestion

SCHEMA = """
CREATE TABLE IF NOT EXISTS minutes (
    ts INTEGER PRIMARY KEY,          -- unix seconds at the start of the minute
    observed_s REAL NOT NULL,
    blinks INTEGER NOT NULL,
    judged INTEGER NOT NULL,
    incomplete INTEGER NOT NULL,
    long_blinks INTEGER NOT NULL,
    max_stare_s REAL NOT NULL,
    distance_cm REAL,
    pitch REAL,
    yaw REAL,
    luminance REAL,
    zones INTEGER NOT NULL,
    switches_per_min REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS breaks (
    ts INTEGER NOT NULL, kind TEXT NOT NULL, outcome TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suggestions (
    ts INTEGER NOT NULL, rule TEXT NOT NULL, severity TEXT NOT NULL, title TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS breaks_ts ON breaks(ts);
CREATE INDEX IF NOT EXISTS suggestions_ts ON suggestions(ts);
"""


class History:
    """Thread-safe (the camera thread writes, the dashboard thread reads)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._migrate()
        self._db.commit()

    # Columns added after v0.1, with defaults so older databases keep working.
    _ADDED = (("session_min", "REAL NOT NULL DEFAULT 0"), ("down_s", "REAL NOT NULL DEFAULT 0"),
              ("obs_down_s", "REAL NOT NULL DEFAULT 0"), ("blinks_down", "INTEGER NOT NULL DEFAULT 0"),
              ("device_switches", "INTEGER NOT NULL DEFAULT 0"), ("stares20", "INTEGER NOT NULL DEFAULT 0"))

    def _migrate(self) -> None:
        have = {r[1] for r in self._db.execute("PRAGMA table_info(minutes)")}
        for name, decl in self._ADDED:
            if name not in have:
                self._db.execute(f"ALTER TABLE minutes ADD COLUMN {name} {decl}")  # noqa: S608

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- writes ---------------------------------------------------------------
    def record(self, ev: Any, wall: float) -> None:
        """Persist an engine event. `wall` is the unix time corresponding to the event."""
        with self._lock:
            if isinstance(ev, MinuteSummary):
                self._db.execute(
                    "INSERT OR REPLACE INTO minutes (ts, observed_s, blinks, judged, incomplete, "
                    "long_blinks, max_stare_s, distance_cm, pitch, yaw, luminance, zones, "
                    "switches_per_min, session_min, down_s, obs_down_s, blinks_down, "
                    "device_switches, stares20) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (int(wall), ev.observed_s, ev.blinks, ev.judged, ev.incomplete, ev.long,
                     ev.max_stare_s, ev.distance_cm, ev.pitch, ev.yaw, ev.luminance, ev.zones,
                     ev.switches_per_min, ev.session_min, ev.down_s, ev.obs_down_s,
                     ev.blinks_down, ev.device_switches, ev.stares20))
            elif isinstance(ev, BreakEnded):
                self._db.execute("INSERT INTO breaks VALUES (?,?,?)", (int(wall), ev.kind, ev.outcome))
            elif isinstance(ev, Suggestion):
                self._db.execute("INSERT INTO suggestions VALUES (?,?,?,?)",
                                 (int(wall), ev.rule, ev.severity, ev.title))
            else:
                return
            self._db.commit()

    def wipe(self) -> None:
        with self._lock:
            for t in ("minutes", "breaks", "suggestions"):
                self._db.execute(f"DELETE FROM {t}")  # noqa: S608 (fixed table names)
            self._db.commit()
            self._db.execute("VACUUM")

    # -- reads ----------------------------------------------------------------
    def daily(self, days: int = 14, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Per-day totals in local time, oldest first."""
        now = now or time.time()
        since = int(now - days * 86400)
        with self._lock:
            rows = self._db.execute(
                """SELECT date(ts, 'unixepoch', 'localtime') AS day,
                          SUM(observed_s), SUM(blinks), SUM(judged), SUM(incomplete),
                          SUM(long_blinks), MAX(max_stare_s), AVG(distance_cm), MAX(zones)
                   FROM minutes WHERE ts >= ? GROUP BY day ORDER BY day""", (since,)).fetchall()
            brk = dict(((d, k, o), n) for d, k, o, n in self._db.execute(
                """SELECT date(ts, 'unixepoch', 'localtime'), kind, outcome, COUNT(*)
                   FROM breaks WHERE ts >= ? GROUP BY 1, 2, 3""", (since,)).fetchall())
        out = []
        for day, obs, blinks, judged, inc, lng, stare, dist, zones in rows:
            obs = obs or 0.0
            done = sum(n for (d, _, o), n in brk.items() if d == day and o in ("rested", "timer"))
            missed = sum(n for (d, _, o), n in brk.items() if d == day and o in ("skipped", "missed"))
            out.append({
                "day": day,
                "screen_minutes": round(obs / 60, 1),
                "blinks": blinks or 0,
                "blink_rate": round(blinks / obs * 60, 1) if obs >= 60 else None,
                "incomplete_ratio": round(inc / judged, 3) if judged else None,
                "long_blinks": lng or 0,
                "longest_stare_s": stare,
                "distance_cm": round(dist) if dist else None,
                "screens": zones,
                "breaks_taken": done,
                "breaks_missed": missed,
            })
        return out

    def minute_rows(self, days: float = 14, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """All per-minute columns for analytics, oldest first."""
        now = now or time.time()
        with self._lock:
            cur = self._db.execute("SELECT * FROM minutes WHERE ts >= ? ORDER BY ts",
                                   (int(now - days * 86400),))
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def minutes(self, hours: float = 8, now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = now or time.time()
        with self._lock:
            cur = self._db.execute(
                "SELECT ts, observed_s, blinks, judged, incomplete, distance_cm "
                "FROM minutes WHERE ts >= ? ORDER BY ts", (int(now - hours * 3600),))
            return [dict(ts=ts, observed_s=o, blinks=b, judged=j, incomplete=i, distance_cm=d)
                    for ts, o, b, j, i, d in cur.fetchall()]

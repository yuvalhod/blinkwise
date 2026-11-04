"""Local history in SQLite: per-minute aggregates only. No images, ever.

Data minimisation: we keep only what a feature actually reads, expire it after
`history_days` (default 90), and give users export and delete. Every column
below is used by the dashboard, the daily summary or the pattern analysis;
see docs/PRIVACY.md for the full inventory.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .events import BreakEnded, MinuteSummary

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS minutes (
    ts INTEGER PRIMARY KEY,          -- unix seconds at the start of the minute
    observed_s REAL NOT NULL,        -- seconds the eyes were measurable (blink-rate denominator)
    blinks INTEGER NOT NULL,
    judged INTEGER NOT NULL,         -- blinks whose completeness could be judged (>= 20 fps)
    incomplete INTEGER NOT NULL,
    long_blinks INTEGER NOT NULL,
    max_stare_s REAL NOT NULL,
    distance_cm REAL,                -- median viewing distance (posture tips)
    zones INTEGER NOT NULL,          -- number of screens in use
    session_min REAL NOT NULL DEFAULT 0,   -- continuous use so far (blink-decay pattern)
    screen_s REAL NOT NULL DEFAULT 0,      -- eyes on the computer screen(s)
    down_s REAL NOT NULL DEFAULT 0,        -- looking down at a phone / other device
    obs_down_s REAL NOT NULL DEFAULT 0,
    blinks_down INTEGER NOT NULL DEFAULT 0,
    device_switches INTEGER NOT NULL DEFAULT 0,
    stares20 INTEGER NOT NULL DEFAULT 0,
    posture_s REAL NOT NULL DEFAULT 0      -- leaning in / chin down / head tilted
);
CREATE TABLE IF NOT EXISTS breaks (
    ts INTEGER NOT NULL, kind TEXT NOT NULL, outcome TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS breaks_ts ON breaks(ts);
CREATE TABLE IF NOT EXISTS checkins (   -- weekly "how do your eyes feel", 0 never .. 3 almost always
    ts INTEGER NOT NULL, dry INTEGER NOT NULL, tired INTEGER NOT NULL, blurry INTEGER NOT NULL
);
"""

_COLS = ("ts", "observed_s", "blinks", "judged", "incomplete", "long_blinks", "max_stare_s",
         "distance_cm", "zones", "session_min", "screen_s", "down_s", "obs_down_s",
         "blinks_down", "device_switches", "stares20", "posture_s")

# Minutes counted as "multitasking": both the computer and another device in the same minute.
MULTI_MIN_EACH_S = 5.0


class History:
    """Thread-safe (the camera thread writes, the dashboard thread reads)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._migrate()
        self._db.executescript(SCHEMA)
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.commit()

    def _migrate(self) -> None:
        """v1 stored head pose, face brightness, switch rates and a suggestions log that no
        feature used. Copy only the needed columns, drop the rest, and VACUUM so the removed
        values are physically gone from the file."""
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in self._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version >= SCHEMA_VERSION or "minutes" not in tables:
            return
        if version == 2:                    # v3 only adds a column
            self._db.execute("ALTER TABLE minutes ADD COLUMN posture_s REAL NOT NULL DEFAULT 0")
            self._db.commit()
            return
        have = {r[1] for r in self._db.execute("PRAGMA table_info(minutes)")}
        self._db.executescript(SCHEMA.replace("CREATE TABLE IF NOT EXISTS minutes",
                                              "CREATE TABLE minutes_v2", 1))
        keep = [c for c in _COLS if c in have]
        cols = ", ".join(keep)
        self._db.execute(f"INSERT INTO minutes_v2 ({cols}) SELECT {cols} FROM minutes")  # noqa: S608
        if "screen_s" not in have:
            # Before screen_s existed, observed time was the best estimate of time on screen.
            self._db.execute("UPDATE minutes_v2 SET screen_s = MAX(0, observed_s - down_s)")
        self._db.execute("DROP TABLE minutes")
        self._db.execute("ALTER TABLE minutes_v2 RENAME TO minutes")
        self._db.execute("DROP TABLE IF EXISTS suggestions")
        self._db.commit()
        self._db.execute("VACUUM")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- writes ---------------------------------------------------------------
    def record(self, ev: Any, wall: float) -> None:
        """Persist an engine event. `wall` is the unix time corresponding to the event."""
        with self._lock:
            if isinstance(ev, MinuteSummary):
                vals = (int(wall), ev.observed_s, ev.blinks, ev.judged, ev.incomplete, ev.long,
                        ev.max_stare_s, ev.distance_cm, ev.zones, ev.session_min, ev.screen_s,
                        ev.down_s, ev.obs_down_s, ev.blinks_down, ev.device_switches, ev.stares20,
                        ev.posture_s)
                self._db.execute(
                    f"INSERT OR REPLACE INTO minutes ({', '.join(_COLS)}) "  # noqa: S608
                    f"VALUES ({', '.join('?' * len(_COLS))})", vals)
            elif isinstance(ev, BreakEnded):
                self._db.execute("INSERT INTO breaks VALUES (?,?,?)", (int(wall), ev.kind, ev.outcome))
            else:
                return               # nothing else is ever stored
            self._db.commit()

    def purge(self, keep_days: float, now: Optional[float] = None) -> int:
        """Delete history older than keep_days. Returns rows removed."""
        cutoff = int((now or time.time()) - keep_days * 86400)
        with self._lock:
            n = self._db.execute("DELETE FROM minutes WHERE ts < ?", (cutoff,)).rowcount
            n += self._db.execute("DELETE FROM breaks WHERE ts < ?", (cutoff,)).rowcount
            n += self._db.execute("DELETE FROM checkins WHERE ts < ?", (cutoff,)).rowcount
            self._db.commit()
        return n

    def wipe(self) -> None:
        with self._lock:
            for t in ("minutes", "breaks", "checkins"):
                self._db.execute(f"DELETE FROM {t}")  # noqa: S608 (fixed table names)
            self._db.commit()
            self._db.execute("VACUUM")

    def export(self) -> Dict[str, Any]:
        """Everything stored, as plain JSON-able data (for the user's own copy)."""
        with self._lock:
            cur = self._db.execute(f"SELECT {', '.join(_COLS)} FROM minutes ORDER BY ts")  # noqa: S608
            minutes = [dict(zip(_COLS, r, strict=True)) for r in cur.fetchall()]
            breaks = [dict(ts=t, kind=k, outcome=o) for t, k, o in
                      self._db.execute("SELECT ts, kind, outcome FROM breaks ORDER BY ts")]
        return {"format": "blinkwise-export", "version": SCHEMA_VERSION,
                "exported_at": int(time.time()), "minutes": minutes, "breaks": breaks,
                "checkins": self.checkins(days=100000)}

    def add_checkin(self, dry: int, tired: int, blurry: int, now: Optional[float] = None) -> None:
        vals = [int(v) for v in (dry, tired, blurry)]
        if any(not 0 <= v <= 3 for v in vals):
            raise ValueError("answers must be 0-3")
        with self._lock:
            self._db.execute("INSERT INTO checkins VALUES (?,?,?,?)", (int(now or time.time()), *vals))
            self._db.commit()

    def checkins(self, days: float = 120, now: Optional[float] = None) -> List[Dict[str, Any]]:
        since = int((now or time.time()) - days * 86400)
        with self._lock:
            rows = self._db.execute("SELECT ts, dry, tired, blurry FROM checkins WHERE ts >= ? "
                                    "ORDER BY ts", (since,)).fetchall()
        return [dict(ts=t, dry=d, tired=ti, blurry=b) for t, d, ti, b in rows]

    # -- reads ----------------------------------------------------------------
    def daily(self, days: int = 14, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Per-day totals in local time, oldest first."""
        now = now or time.time()
        since = int(now - days * 86400)
        with self._lock:
            rows = self._db.execute(
                """SELECT date(ts, 'unixepoch', 'localtime') AS day,
                          SUM(observed_s), SUM(blinks), SUM(judged), SUM(incomplete),
                          SUM(long_blinks), MAX(max_stare_s), AVG(distance_cm), MAX(zones),
                          SUM(screen_s), SUM(down_s),
                          SUM(CASE WHEN screen_s >= ? AND down_s >= ? THEN 1 ELSE 0 END),
                          SUM(device_switches), SUM(posture_s)
                   FROM minutes WHERE ts >= ? GROUP BY day ORDER BY day""",
                (MULTI_MIN_EACH_S, MULTI_MIN_EACH_S, since)).fetchall()
            brk = dict(((d, k, o), n) for d, k, o, n in self._db.execute(
                """SELECT date(ts, 'unixepoch', 'localtime'), kind, outcome, COUNT(*)
                   FROM breaks WHERE ts >= ? GROUP BY 1, 2, 3""", (since,)).fetchall())
        out = []
        for (day, obs, blinks, judged, inc, lng, stare, dist, zones, scr, down, multi,
             switches, posture) in rows:
            obs = obs or 0.0
            done = sum(n for (d, _, o), n in brk.items() if d == day and o in ("rested", "timer"))
            missed = sum(n for (d, _, o), n in brk.items() if d == day and o in ("skipped", "missed"))
            out.append({
                "day": day,
                "screen_minutes": round((scr or 0) / 60, 1),     # eyes on the computer
                "device_minutes": round((down or 0) / 60, 1),    # phone / other device
                "multitask_minutes": int(multi or 0),            # both in the same minute
                "device_switches": int(switches or 0),
                "posture_minutes": round((posture or 0) / 60, 1),
                "blinks": blinks or 0,
                "observed_minutes": round(obs / 60, 1),
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
            cur = self._db.execute(f"SELECT {', '.join(_COLS)} FROM minutes WHERE ts >= ? "  # noqa: S608
                                   "ORDER BY ts", (int(now - days * 86400),))
            return [dict(zip(_COLS, r, strict=True)) for r in cur.fetchall()]

    def minutes(self, hours: float = 8, now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = now or time.time()
        with self._lock:
            cur = self._db.execute(
                "SELECT ts, observed_s, blinks, screen_s, down_s FROM minutes WHERE ts >= ? "
                "ORDER BY ts", (int(now - hours * 3600),))
            return [dict(ts=ts, observed_s=o, blinks=b, screen_s=s, down_s=d)
                    for ts, o, b, s, d in cur.fetchall()]

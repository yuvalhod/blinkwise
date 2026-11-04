"""Posture: leaning in, chin down, head tilt, against the user's own baseline."""

import sqlite3

from blinkwise.config import Settings
from blinkwise.core.engine import Engine
from blinkwise.core.events import MinuteSummary, Suggestion
from blinkwise.core.posture import PostureTracker
from blinkwise.core.simulate import Scenario, Screen, Simulation
from blinkwise.core.storage import History

M = 60.0


def run(sc):
    eng = Engine(Settings(notify_suggestions="all"), monitors=1)
    sugg, minutes, states = [], [], []
    for f in Simulation(sc).frames():
        for ev in eng.step(f):
            if isinstance(ev, Suggestion) and ev.rule == "posture":
                sugg.append((f.t, ev.data["pattern"]))
            elif isinstance(ev, MinuteSummary):
                minutes.append(ev)
        if int(f.t * sc.fps) % sc.fps == 0:
            states.append((f.t, eng.posture.current))
    return eng, sugg, minutes, states


def state_at(states, t):
    return min(states, key=lambda s: abs(s[0] - t))[1]


def test_each_pattern_detected_and_nudged():
    sc = Scenario(duration_s=40 * M, fps=10, blink_rate=12, seed=4,
                  lean_windows=[(10 * M, 15 * M)], slump_windows=[(20 * M, 25 * M)],
                  tilt_windows=[(30 * M, 35 * M)])
    eng, sugg, minutes, states = run(sc)
    assert state_at(states, 12 * M) == "leaning_in"
    assert state_at(states, 22 * M) == "chin_down"
    assert state_at(states, 32 * M) == "head_tilt"
    for t in (8 * M, 17 * M, 27 * M, 38 * M):
        assert state_at(states, t) is None, t
    patterns = [p for _, p in sugg]
    # One posture nudge per 20 minutes at most: chin-down (10 min after the lean-in nudge)
    # is detected and counted, but not nudged.
    assert patterns == ["leaning_in", "head_tilt"]
    for t, p in sugg:                          # nudged 3-4 minutes into each pattern
        start = {"leaning_in": 10, "chin_down": 20, "head_tilt": 30}[p] * M
        assert start + 180 <= t <= start + 260
    total = sum(m.posture_s for m in minutes) / M
    assert 13 <= total <= 15.5                # ~3 x (5 min - 20 s to confirm)


def test_chin_down_nudge():
    sc = Scenario(duration_s=16 * M, fps=10, blink_rate=12, seed=6, slump_windows=[(8 * M, 14 * M)])
    _, sugg, _, _ = run(sc)
    assert [p for _, p in sugg] == ["chin_down"] and 8 * M + 180 <= sugg[0][0] <= 8 * M + 260


def test_good_posture_and_two_screens_stay_quiet():
    """A laptop 15 degrees below the monitor is not "chin down"; keyboard glances aren't either."""
    sc = Scenario(duration_s=40 * M, fps=10, blink_rate=12, seed=9,
                  screens=(Screen(-5, -2, 0.6), Screen(30, -17, 0.4)), dwell_s=40,
                  keyboard_glances_per_min=2)
    eng, sugg, minutes, _ = run(sc)
    assert sugg == []
    assert sum(m.posture_s for m in minutes) < 60
    assert eng.snapshot()["posture"] == "Good"


def test_needs_a_baseline_first():
    p = PostureTracker()
    for i in range(200):
        assert p.update(i * 1.0, 1.0, True, -30.0, 30.0, 30.0) is None   # bad, but no baseline yet
    assert Engine(Settings(), monitors=1).snapshot()["posture"] is None


def test_storage_v2_gets_posture_column(tmp_path):
    db = sqlite3.connect(tmp_path / "h.sqlite")
    cols = ("ts INTEGER PRIMARY KEY, observed_s REAL, blinks INTEGER, judged INTEGER, incomplete INTEGER,"
            " long_blinks INTEGER, max_stare_s REAL, distance_cm REAL, zones INTEGER, session_min REAL,"
            " screen_s REAL, down_s REAL, obs_down_s REAL, blinks_down INTEGER,"
            " device_switches INTEGER, stares20 INTEGER")
    db.execute(f"CREATE TABLE minutes ({cols})")
    db.execute("INSERT INTO minutes VALUES (1000,60,10,10,2,0,5,60,1,1,60,0,0,0,0,0)")
    db.execute("PRAGMA user_version = 2")
    db.commit()
    db.close()
    h = History(tmp_path / "h.sqlite")
    rows = h.minute_rows(days=1e6, now=2000)
    assert rows[0]["posture_s"] == 0 and rows[0]["blinks"] == 10
    h.record(MinuteSummary(t=0, observed_s=60, blinks=12, judged=0, incomplete=0, long=0,
                           max_stare_s=3, distance_cm=55, zones=1, screen_s=60, posture_s=42.0), 5000)
    assert h.minute_rows(days=1e6, now=6000)[-1]["posture_s"] == 42.0
    h.close()

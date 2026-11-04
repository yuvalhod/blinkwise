import json
import time
import urllib.error
import urllib.request

import pytest

from blinkwise.core.events import BreakEnded, MinuteSummary, Suggestion
from blinkwise.core.storage import History
from blinkwise.ui.dashboard import DashboardServer


def _minute(blinks=8, screen_s=60.0, down_s=0.0):
    return MinuteSummary(t=0, observed_s=60, blinks=blinks, judged=blinks, incomplete=2, long=0,
                         max_stare_s=12, distance_cm=55, zones=2, screen_s=screen_s, down_s=down_s)


def _noon():
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))


def test_history_daily_rollup_with_screen_time(tmp_path):
    h = History(tmp_path / "h.sqlite")
    now = _noon()
    for i in range(10):
        # minutes 0-6 computer only; 7-9 computer + phone (multitasking)
        h.record(_minute(screen_s=40.0 if i >= 7 else 60.0, down_s=20.0 if i >= 7 else 0.0),
                 now - 600 + i * 60)
    h.record(BreakEnded("micro", "rested"), now)
    h.record(BreakEnded("micro", "skipped"), now)
    h.record(Suggestion("low_blink_rate", "warn", "t", "m"), now)       # not stored
    day = h.daily(7, now=now + 3600)[-1]
    assert day["blink_rate"] == 8.0
    assert day["screen_minutes"] == 9.0 and day["device_minutes"] == 1.0
    assert day["multitask_minutes"] == 3
    assert day["incomplete_ratio"] == 0.25
    assert (day["breaks_taken"], day["breaks_missed"]) == (1, 1)
    assert len(h.minutes(1, now=now)) == 10
    h.wipe()
    assert h.daily(7, now=now + 3600) == []


def test_minimal_columns_only_and_no_suggestion_log(tmp_path):
    h = History(tmp_path / "h.sqlite")
    cols = {r[1] for r in h._db.execute("PRAGMA table_info(minutes)")}
    assert not cols & {"pitch", "yaw", "luminance", "switches_per_min"}
    tables = {r[0] for r in h._db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"minutes", "breaks", "checkins"}


def test_v1_database_is_migrated_and_scrubbed(tmp_path):
    import sqlite3
    p = tmp_path / "old.sqlite"
    db = sqlite3.connect(p)
    db.executescript("""
        CREATE TABLE minutes (ts INTEGER PRIMARY KEY, observed_s REAL NOT NULL, blinks INTEGER NOT NULL,
            judged INTEGER NOT NULL, incomplete INTEGER NOT NULL, long_blinks INTEGER NOT NULL,
            max_stare_s REAL NOT NULL, distance_cm REAL, pitch REAL, yaw REAL, luminance REAL,
            zones INTEGER NOT NULL, switches_per_min REAL NOT NULL);
        CREATE TABLE breaks (ts INTEGER NOT NULL, kind TEXT NOT NULL, outcome TEXT NOT NULL);
        CREATE TABLE suggestions (ts INTEGER, rule TEXT, severity TEXT, title TEXT);
        INSERT INTO minutes VALUES (1000, 60, 9, 9, 1, 0, 8, 61, -4.2, 3.1, 117.5, 1, 0.5);
        INSERT INTO suggestions VALUES (1000, 'x', 'warn', 'secret-looking title');""")
    db.commit()
    db.close()
    h = History(p)
    rows = h.minute_rows(days=1e6)
    assert rows[0]["blinks"] == 9 and rows[0]["screen_s"] == 60 and "pitch" not in rows[0]
    h.close()
    raw = p.read_bytes()
    assert b"secret-looking title" not in raw                     # vacuumed, physically gone


def test_purge_and_export(tmp_path):
    h = History(tmp_path / "h.sqlite")
    now = time.time()
    h.record(_minute(), now - 100 * 86400)
    h.record(_minute(), now - 60)
    assert h.purge(90, now=now) == 1
    ex = h.export()
    assert ex["format"] == "blinkwise-export" and len(ex["minutes"]) == 1
    assert set(ex["minutes"][0]) == {"ts", "observed_s", "blinks", "judged", "incomplete",
                                     "long_blinks", "max_stare_s", "distance_cm", "zones",
                                     "session_min", "screen_s", "down_s", "obs_down_s",
                                     "blinks_down", "device_switches", "stares20", "posture_s"}


@pytest.fixture
def server(tmp_path):
    actions = []
    srv = DashboardServer(18765, get_snapshot=lambda: {"blink_rate_5m": 7.0},
                          history=History(tmp_path / "h.sqlite"),
                          on_action=lambda a: actions.append(a) or {"ok": True})
    srv.start()
    yield srv, actions
    srv.stop()


def _get(url, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=5)


def test_dashboard_serves_page_and_api(server):
    srv, _ = server
    html = _get(srv.url).read().decode()
    assert "Blinkwise" in html and srv.token in html
    live = json.load(_get(srv.url + "api/live"))
    assert live == {"running": True, "blink_rate_5m": 7.0}
    assert json.load(_get(srv.url + "api/history"))["daily"] == []
    assert len(json.load(_get(srv.url + "api/science"))) >= 10


def test_dashboard_rejects_foreign_host_and_missing_token(server):
    srv, actions = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(srv.url + "api/live", {"Host": "attacker.example"})
    assert e.value.code == 403
    req = urllib.request.Request(srv.url + "api/action", data=b'{"action":"pause"}', method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403
    req.add_header("X-Blinkwise-Token", srv.token)
    assert json.load(urllib.request.urlopen(req, timeout=5)) == {"ok": True}
    bad = urllib.request.Request(srv.url + "api/action", data=b'{"action":"rm -rf"}', method="POST",
                                 headers={"X-Blinkwise-Token": srv.token})
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(bad, timeout=5)
    assert actions == ["pause"]


def test_export_download_and_wipe_action(tmp_path):
    h = History(tmp_path / "h.sqlite")
    h.record(_minute(), time.time() - 60)
    wiped = []
    srv = DashboardServer(18766, history=h,
                          on_action=lambda a: (wiped.append(a), h.wipe()) and {"ok": True})
    srv.start()
    try:
        r = _get(srv.url + "api/export")
        assert "attachment" in r.headers["Content-Disposition"]
        data = json.load(r)
        assert len(data["minutes"]) == 1 and "pitch" not in data["minutes"][0]
        req = urllib.request.Request(srv.url + "api/action", data=b'{"action":"wipe"}', method="POST",
                                     headers={"X-Blinkwise-Token": srv.token})
        urllib.request.urlopen(req, timeout=5)
        assert wiped == ["wipe"] and json.load(_get(srv.url + "api/export"))["minutes"] == []
    finally:
        srv.stop()

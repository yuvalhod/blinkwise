import json
import time
import urllib.error
import urllib.request

import pytest

from blinkwise.core.events import BreakEnded, MinuteSummary, Suggestion
from blinkwise.core.storage import History
from blinkwise.ui.dashboard import DashboardServer


def _minute(blinks=8):
    return MinuteSummary(t=0, observed_s=60, blinks=blinks, judged=blinks, incomplete=2, long=0,
                         max_stare_s=12, distance_cm=55, pitch=-4, yaw=0, luminance=100,
                         zones=2, switches_per_min=1.0)


def test_history_daily_rollup(tmp_path):
    h = History(tmp_path / "h.sqlite")
    # Anchor at local noon so the 10 minutes never straddle midnight.
    lt = time.localtime()
    now = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
    for i in range(10):
        h.record(_minute(), now - 600 + i * 60)
    h.record(BreakEnded("micro", "rested"), now)
    h.record(BreakEnded("micro", "skipped"), now)
    h.record(Suggestion("low_blink_rate", "warn", "t", "m"), now)
    days = h.daily(7, now=now + 3600)
    assert days[-1]["blink_rate"] == 8.0 and days[-1]["screen_minutes"] == 10.0
    assert days[-1]["incomplete_ratio"] == 0.25
    assert (days[-1]["breaks_taken"], days[-1]["breaks_missed"]) == (1, 1)
    assert len(h.minutes(1, now=now)) == 10
    h.wipe()
    assert h.daily(7) == []


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

"""Weekly check-in and weekly report."""

import json
import time
import urllib.request
from datetime import date, timedelta

import pytest

from blinkwise.core import weekly
from blinkwise.core.storage import History
from blinkwise.ui.menu import build_menu

DAY = 86400


def c(ts, dry, tired, blurry):
    return {"ts": ts, "dry": dry, "tired": tired, "blurry": blurry}


def test_checkin_schedule():
    now = 1_000 * DAY
    assert not weekly.checkin_due([], days_used=2, now=now)
    assert weekly.checkin_due([], days_used=3, now=now)
    assert not weekly.checkin_due([c(now - 3 * DAY, 0, 0, 0)], 10, now=now)
    assert weekly.checkin_due([c(now - 7 * DAY + 1800, 0, 0, 0)], 10, now=now)   # same time next week


def test_advice_escalates_only_when_persistent_or_severe():
    t = 1_000 * DAY
    assert weekly.checkin_advice([]) is None
    assert weekly.checkin_advice([c(t, 1, 1, 0)])["level"] == "good"
    assert weekly.checkin_advice([c(t, 2, 2, 2)])["level"] == "watch"          # one bad week
    assert weekly.checkin_advice([c(t - 7 * DAY, 2, 2, 2), c(t, 2, 2, 2)])["level"] == "doctor"
    assert weekly.checkin_advice([c(t, 3, 0, 0)])["level"] == "doctor"         # "almost always"
    better = weekly.checkin_advice([c(t - 7 * DAY, 2, 2, 1), c(t, 1, 1, 0)])
    assert better["title"] == "Better than last week"


def day(d, **kw):
    base = dict(day=d.isoformat(), screen_minutes=300, device_minutes=40, observed_minutes=300,
                blinks=300 * 9, incomplete_ratio=0.3, distance_cm=60, breaks_taken=8, breaks_missed=2)
    base.update(kw)
    return base


def test_report_compares_weeks_and_picks_one_goal():
    today = date(2026, 11, 4)
    days = [day(today - timedelta(days=i), blinks=300 * 12) for i in range(7, 14)]   # last week: 12/min
    days += [day(today - timedelta(days=i)) for i in range(0, 5)]                     # this week: 9/min
    r = weekly.report(days, today=today)
    rows = {x["key"]: x for x in r["rows"]}
    assert r["days_this_week"] == 5
    assert rows["blink_rate"]["this"] == 9.0 and rows["blink_rate"]["last"] == 12.0
    assert rows["blink_rate"]["trend"] == "worse"
    assert rows["screen_per_day"]["this"] == 300 and rows["breaks_pct"]["this"] == 80
    assert rows["full_blinks"]["this"] == 70
    assert r["goal"]["key"] == "blink_rate" and r["goal"]["target"] == "11"


def test_goal_priorities():
    assert weekly.pick_goal({"blink_rate": 14})["key"] == "keep"
    assert weekly.pick_goal({"blink_rate": 14}, {"dry": 2})["key"] == "blink_rate"   # symptoms first
    assert weekly.pick_goal({"blink_rate": 14, "breaks_pct": 40})["key"] == "breaks_pct"
    assert weekly.pick_goal({"distance_cm": 42})["key"] == "distance_cm"
    assert weekly.pick_goal({"phone_per_day": 150})["target"] == "120"


def test_last_weeks_goal_is_checked():
    today = date(2026, 11, 4)
    days = [day(today - timedelta(days=i), blinks=300 * 8) for i in range(7, 14)]   # goal: 10/min
    days += [day(today - timedelta(days=i), blinks=300 * 11) for i in range(0, 7)]
    r = weekly.report(days, today=today)
    assert r["last_goal"]["key"] == "blink_rate" and r["last_goal_met"] is True


def test_empty_history_report():
    r = weekly.report([], today=date(2026, 11, 4))
    assert not r["has_data"] and r["rows"] == [] and r["goal"]["key"] == "keep"


def test_checkins_storage_lifecycle(tmp_path):
    h = History(tmp_path / "h.sqlite")
    now = time.time()
    h.add_checkin(1, 2, 0, now=now - 200 * DAY)
    h.add_checkin(0, 1, 3, now=now)
    with pytest.raises(ValueError):
        h.add_checkin(4, 0, 0)
    assert [x["blurry"] for x in h.checkins()] == [3]                  # 120-day default window
    assert len(h.export()["checkins"]) == 2
    h.purge(90)
    assert len(h.export()["checkins"]) == 1
    h.wipe()
    assert h.checkins() == []
    h.close()


def test_dashboard_weekly_and_checkin_api(tmp_path):
    from blinkwise.ui.dashboard import DashboardServer
    h = History(tmp_path / "h.sqlite")
    srv = DashboardServer(0, history=h)
    url = srv.start()
    try:
        w = json.load(urllib.request.urlopen(url + "api/weekly"))
        assert w["checkin"]["due"] is False and len(w["checkin"]["questions"]) == 3

        def post(body, token=srv.token):
            req = urllib.request.Request(url + "api/checkin", json.dumps(body).encode(),
                                         {"Content-Type": "application/json", "X-Blinkwise-Token": token})
            return urllib.request.urlopen(req)
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"dry": 1, "tired": 1, "blurry": 1}, token="nope")
        assert e.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"dry": 9, "tired": 1, "blurry": 1})
        assert e.value.code == 400
        with pytest.raises(urllib.error.HTTPError):
            post({"dry": 1})
        res = json.load(post({"dry": 3, "tired": 1, "blurry": 0}))
        assert res["checkin"]["advice"]["level"] == "doctor" and res["checkin"]["due"] is False
    finally:
        srv.stop()
        h.close()


def test_menu_offers_checkin_when_due():
    texts = [i.text for i in build_menu({"face": True, "checkin_due": True}, blink_cue="subtle",
                                        autostart=None)]
    assert "Weekly eye check-in..." in texts

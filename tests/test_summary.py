import time

from blinkwise.core import summary


def d(day, minutes=300, rate=9.0, taken=6, missed=2):
    return dict(day=day, screen_minutes=minutes, blink_rate=rate, breaks_taken=taken, breaks_missed=missed)


def test_summary_compares_with_own_average():
    days = [d("2026-10-30", rate=8), d("2026-10-31", rate=8), d("2026-11-01", rate=11)]
    title, msg = summary.build(days, today="2026-11-01")
    assert title == "Your eyes today"
    assert "5 h 00 min on screen" in msg and "blinked 11/min (recent average 8)" in msg
    assert "Nice: you blinked more than your recent average" in msg
    assert "6 of 8 breaks" in msg


def test_summary_suggests_something_and_stays_quiet_on_light_days():
    days = [d("2026-10-31", rate=12), d("2026-11-01", rate=8, taken=1, missed=5)]
    _, msg = summary.build(days, today="2026-11-01")
    assert "Tomorrow: you blinked less than usual" in msg
    assert summary.build([d("2026-11-01", minutes=12)], today="2026-11-01") is None
    assert summary.build([], today="2026-11-01") is None


def test_summary_due_logic():
    lt = time.localtime()
    noon = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
    today = time.strftime("%Y-%m-%d", time.localtime(noon))
    assert summary.due("11:30", None, noon)
    assert not summary.due("18:00", None, noon)
    assert not summary.due("11:30", today, noon)          # already sent today
    assert not summary.due("", None, noon)

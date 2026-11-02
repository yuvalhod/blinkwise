import time

from blinkwise.core.analytics import blink_decay, by_hour, devices, insights, posture_drift, report

BASE = time.mktime(time.strptime("2026-11-02 09:00", "%Y-%m-%d %H:%M"))


def day(minutes=240, rate=lambda m, i: 15.0, session_reset=60, down_every=None, down_rate=0.6,
        dist=lambda i: 60.0, start=BASE):
    rows = []
    for i in range(minutes):
        m = i % session_reset
        down = bool(down_every) and (i % down_every) < 2
        r = rate(m, i)
        obs_down = 50.0 if down else 0.0
        total = round(r * (1 - (1 - down_rate) * down * 50 / 60))
        rows.append(dict(ts=int(start + i * 60), observed_s=60.0, blinks=total,
                         session_min=float(m), down_s=obs_down, obs_down_s=obs_down,
                         blinks_down=round(r * down_rate * 50 / 60) if down else 0,
                         device_switches=2 if down and i % down_every == 0 else 0,
                         stares20=1 if i % 5 == 0 else 0, distance_cm=dist(i)))
    return rows


def test_decay_finds_when_blinking_drops():
    rows = day(rate=lambda m, i: 16 * (1 - 0.6 * m / 60))
    d = blink_decay(rows)
    assert d["fresh_rate"] > 14
    assert d["fatigue_after_min"] == 20          # 20% below fresh is reached in the 20-30 bin
    ins = {i.key: i for i in insights(rows)}
    assert "decay" in ins and ins["decay"].data["suggested_break_min"] == 20


def test_no_decay_no_insight_and_too_little_data_says_nothing():
    assert blink_decay(day())["fatigue_after_min"] is None
    assert report(day(minutes=10))["insights"] == []


def test_devices_share_switches_and_rates():
    dv = devices(day(down_every=10))
    assert 0.12 < dv["down_share"] < 0.2
    assert 5 < dv["switches_per_hour"] < 15
    assert dv["rate_down"] < dv["rate_screen"]
    assert any(i.key == "devices" for i in insights(day(down_every=10)))


def test_time_of_day_and_posture_drift():
    rows = day(minutes=480, rate=lambda m, i: 8 if 4 * 60 <= i < 5 * 60 else 16,
               dist=lambda i: 65 - i / 480 * 15)
    lows = [h for h in by_hour(rows) if h["rate"] and h["rate"] < 10]
    assert [h["hour"] for h in lows] == [13]
    keys = {i.key for i in insights(rows)}
    assert {"hour", "posture"} <= keys
    pd = posture_drift(rows)
    assert pd["early_cm"] - pd["late_cm"] >= 8

import pytest

from blinkwise.config import Settings
from blinkwise.core.coach import Coach, CoachContext, poisson_rate_p_value
from blinkwise.core.metrics import WindowStats
from blinkwise.research import REFERENCES
from blinkwise.vision.attention import Zone


def ws(rate=15.0, obs=300.0, inc=None, lng=0.0):
    return WindowStats(obs, obs, int((rate or 0) * obs / 60), rate, inc, lng)


def ctx(now=1000.0, **kw):
    base = dict(now=now, s1=ws(), s5=ws(), s10=ws(obs=600), distance_cm=60.0, pitch=-5.0,
                luminance=110.0, zones=[], monitors=1, switches_per_min=0.0,
                screen_minutes=30.0, fps=30.0)
    base.update(kw)
    return CoachContext(**base)


def rules(c, settings=None):
    return {s.rule: s for s in Coach(settings or Settings()).evaluate(c)}


def test_healthy_user_gets_nothing():
    assert rules(ctx()) == {}


def test_low_blink_rate_severity():
    assert rules(ctx(s5=ws(rate=8)))["low_blink_rate"].severity == "warn"
    assert rules(ctx(s5=ws(rate=4)))["low_blink_rate"].severity == "high"
    assert "low_blink_rate" not in rules(ctx(s5=ws(rate=4, obs=100)))   # not enough data


def test_incomplete_and_distance_and_light():
    r = rules(ctx(s10=ws(obs=600, inc=0.5), distance_cm=40, luminance=30))
    assert {"incomplete_blinks", "too_close", "dim_light"} <= set(r)


def test_multi_screen_advice_mentions_head_turn():
    zones = [Zone(0, -3, -5, 0.6, 10, 600), Zone(1, 42, -5, 0.4, 10, 400)]
    s = rules(ctx(zones=zones, monitors=3))["multi_screen"]
    assert "42 degree" in s.message and "3 displays" in s.message and s.severity == "warn"


def test_zone_blink_gap_requires_significance():
    noisy = [Zone(0, 0, -5, .5, 12, 300), Zone(1, 30, -5, .5, 6, 300)]   # 60 vs 30 blinks
    real = [Zone(0, 0, -5, .5, 14, 1200), Zone(1, 30, -5, .5, 6, 1200)]
    assert "screen_zone_blink_gap" not in rules(ctx(zones=[Zone(0, 0, -5, .5, 12, 100),
                                                         Zone(1, 30, -5, .5, 6, 100)]))
    assert "screen_zone_blink_gap" in rules(ctx(zones=real))
    assert poisson_rate_p_value(30, 300, 60, 300) < 0.01 or "screen_zone_blink_gap" in rules(ctx(zones=noisy))


def test_poisson_p_value_sane():
    assert poisson_rate_p_value(50, 600, 50, 600) > 0.9
    assert poisson_rate_p_value(20, 600, 80, 600) < 1e-6
    assert poisson_rate_p_value(1, 600, 5, 600) == 1.0   # too little data to say anything


def test_cooldown_and_single_notification():
    coach = Coach(Settings())
    first = coach.evaluate(ctx(s5=ws(rate=4), distance_cm=40))
    assert sum(s.notify for s in first) == 1 and first[0].severity == "high"
    assert coach.evaluate(ctx(now=1010, s5=ws(rate=4), distance_cm=40)) == []


def test_young_profile_gets_outdoor_advice():
    assert "young_outdoors" in rules(ctx(screen_minutes=90), Settings(profile="young"))
    assert "young_outdoors" not in rules(ctx(screen_minutes=90))


def test_every_reference_used_exists():
    import inspect

    from blinkwise.core import coach
    src = inspect.getsource(coach)
    import re
    for key in re.findall(r'refs=\[([^\]]*)\]', src):
        for k in re.findall(r'"(\w+)"', key):
            assert k in REFERENCES, k


@pytest.mark.parametrize("key", list(REFERENCES))
def test_references_complete(key):
    r = REFERENCES[key]
    assert r.citation and r.finding and r.url.startswith("https://")

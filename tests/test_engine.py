import json

from blinkwise.config import Settings
from blinkwise.core.engine import Engine
from blinkwise.core.events import BlinkEvent, BreakDue, MinuteSummary, StareCue, Suggestion
from blinkwise.core.simulate import Scenario, Screen, Simulation
from blinkwise.vision.features import FrameFeatures


def run(sc, settings=None):
    eng = Engine(settings or Settings(), monitors=2)
    evs = []
    for f in Simulation(sc).frames():
        evs += eng.step(f)
    return eng, evs


def test_engine_end_to_end_low_blinker():
    sc = Scenario(duration_s=25 * 60, fps=15, blink_rate=6, incomplete_frac=0.5, distance_cm=42,
                  screens=(Screen(-3, share=.6), Screen(30, share=.4)), seed=8)
    eng, evs = run(sc)
    kinds = {type(e) for e in evs}
    assert {BlinkEvent, MinuteSummary, StareCue, Suggestion, BreakDue} <= kinds
    rules = {e.rule for e in evs if isinstance(e, Suggestion)}
    assert {"low_blink_rate", "too_close", "multi_screen"} <= rules
    # 15 fps -> completeness intentionally unavailable, so no incomplete-blink advice.
    assert "incomplete_blinks" not in rules
    snap = eng.snapshot()
    json.dumps(snap)                                    # must be serialisable for the dashboard
    assert 3 < snap["blink_rate_10m"] < 9
    assert len(snap["zones"]) == 2
    assert len({s["rule"] for s in snap["suggestions"]}) == len(snap["suggestions"])
    assert sum(isinstance(e, MinuteSummary) for e in evs) >= 24


def test_healthy_blinker_gets_no_stare_cues_and_no_blink_warnings():
    eng, evs = run(Scenario(duration_s=10 * 60, blink_rate=20, seed=3))
    rules = {e.rule for e in evs if isinstance(e, Suggestion)}
    assert "low_blink_rate" not in rules
    cues = sum(isinstance(e, StareCue) for e in evs)
    assert cues <= 3


def test_stare_cue_fires_after_threshold_and_respects_off():
    def staring(settings):
        eng = Engine(settings, monitors=1)
        out = []
        for i in range(30 * 25):
            out += eng.step(FrameFeatures(t=i / 30, face=True, ear_right=.3, ear_left=.3,
                                          width_right=30, width_left=30))
        return [e for e in out if isinstance(e, StareCue)]
    cues = staring(Settings(stare_seconds=8))
    assert 2 <= len(cues) <= 3 and cues[0].seconds_since_blink >= 8
    assert staring(Settings(blink_cue="off")) == []


def test_absence_resets_stare_timer():
    eng = Engine(Settings(), monitors=1)
    for i in range(150):
        eng.step(FrameFeatures(t=i / 30, face=True, ear_right=.3, ear_left=.3, width_right=30, width_left=30))
    for i in range(150, 300):
        eng.step(FrameFeatures(t=i / 30, face=False))
    eng.step(FrameFeatures(t=10.1, face=True, ear_right=.3, ear_left=.3, width_right=30, width_left=30))
    assert eng.seconds_since_blink < 0.5

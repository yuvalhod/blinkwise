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


def test_perclos_flags_drowsiness_but_not_normal_blinking_or_rest():
    drowsy = Scenario(duration_s=8 * 60, fps=20, blink_rate=15, long_frac=0.7, long_hold_s=1.6, seed=4)
    eng, evs = run(drowsy)
    assert eng.snapshot()["perclos_5m"] >= 0.15
    assert any(isinstance(e, Suggestion) and e.rule == "fatigue" and e.severity == "high" for e in evs)

    alert = Scenario(duration_s=8 * 60, fps=20, blink_rate=18, seed=4)
    eng, evs = run(alert)
    assert eng.snapshot()["perclos_5m"] < 0.06
    assert not any(isinstance(e, Suggestion) and e.rule == "fatigue" for e in evs)


def test_resting_eyes_closed_is_not_counted_as_drowsiness():
    eng = Engine(Settings(), monitors=1)
    t = 0.0
    for _ in range(int(240 * 20)):         # 4 min: open, with one 30 s eyes-closed rest
        t += 0.05
        closed = 100 < t < 130
        ear = 0.03 if closed else 0.3
        eng.step(FrameFeatures(t=t, face=True, ear_right=ear, ear_left=ear, width_right=30,
                               width_left=30, face_px=140, luminance=110))
    assert (eng.snapshot()["perclos_5m"] or 0) < 0.02

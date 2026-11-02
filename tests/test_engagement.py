from blinkwise.config import PRESETS, Settings
from blinkwise.core.engagement import CueResponse, Escalator
from blinkwise.core.engine import Engine
from blinkwise.core.events import StareCue
from blinkwise.vision.features import FrameFeatures


def test_cue_response_rate():
    r = CueResponse()
    for i in range(6):
        r.cue(i * 10.0)
        if i % 2 == 0:
            r.blink(i * 10.0 + 2.0)          # responded within 4 s
        r.tick(i * 10.0 + 5.0)
    assert r.rate() == 0.5


def test_escalator_steps_up_when_ignored_and_down_when_responsive():
    e = Escalator(start="menubar")
    t = 0.0
    for _ in range(6):                        # ignored
        e.on_cue(t)
        t += 10
        e.tick(t)
    assert e.cue == "subtle"
    for _ in range(6):
        e.on_cue(t)
        t += 10
        e.tick(t)
    assert e.cue == "big"                     # never beyond the top
    for _ in range(6):                        # now responsive
        e.on_cue(t)
        e.on_blink(t + 1)
        t += 10
        e.tick(t)
    assert e.cue == "subtle"


def _stare(eng, seconds, t0=0.0):
    out = []
    for i in range(int(seconds * 20)):
        out += eng.step(FrameFeatures(t=t0 + i / 20, face=True, ear_right=.3, ear_left=.3,
                                      width_right=30, width_left=30, face_px=140, luminance=110))
    return out


def test_engine_escalates_cue_for_someone_who_ignores_it():
    s = Settings(blink_cue="menubar", adaptive_cues=True, stare_seconds=6)
    eng = Engine(s, monitors=1)
    cues = [e for e in _stare(eng, 120) if isinstance(e, StareCue)]
    assert cues[0].style == "menubar"
    assert cues[-1].style in ("subtle", "big")
    assert eng.snapshot()["cue_response_rate"] is not None


def test_non_adaptive_cue_never_changes():
    s = Settings(blink_cue="menubar", adaptive_cues=False, stare_seconds=6)
    cues = [e for e in _stare(Engine(s, monitors=1), 120) if isinstance(e, StareCue)]
    assert {c.style for c in cues} == {"menubar"}


def test_presets_and_ui_validation():
    s = Settings().apply_preset("gentle")
    assert (s.blink_cue, s.break_style, s.micro_break_minutes) == ("menubar", "notify", 30.0)
    s.apply_ui_changes({"preset": "coach"})
    assert s.preset == "coach" and s.blink_cue == "big" and s.break_style == "immersive"
    s.apply_ui_changes({"stare_seconds": "12"})
    assert s.preset == "custom" and s.stare_seconds == 12.0
    for bad in ({"stare_seconds": 1}, {"blink_cue": "explode"}, {"daily_summary": "25:00"}):
        try:
            s.apply_ui_changes(bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    s.apply_ui_changes({"not_a_setting": 1, "dashboard_port": 1})   # ignored, not editable
    assert s.dashboard_port == 8765
    assert set(PRESETS) == {"gentle", "balanced", "coach"}

"""Personal blink calibration: cued blinks, still eyes, keyboard glances."""

import pytest

from blinkwise import calibration as C
from blinkwise.core.simulate import Scenario, Simulation
from blinkwise.vision.blink import BlinkDetector, BlinkParams
from blinkwise.vision.features import FrameFeatures

FPS = 15


def recording(depth=(0.05, 0.15), noise=0.008, react=0.45, seed=7):
    """A simulated person doing the calibration routine."""
    down0 = {st.key: a for st, a, _ in C.plan()}["down"]
    sc = Scenario(duration_s=C.TOTAL_S + 1, fps=FPS, blink_times=[c + react for c in C.cue_times()],
                  blink_depth=depth, ear_noise=noise, seed=seed,
                  glance_windows=[(down0 + a, down0 + b) for a, b in C.DOWN_WINDOWS])
    return list(Simulation(sc).frames())


def recall_and_false(params, depth, seed=3):
    """Held-out check: a 5-minute session of the same person, random blinks and glances."""
    sim = Simulation(Scenario(duration_s=300, fps=FPS, blink_rate=14, blink_depth=depth,
                              keyboard_glances_per_min=2, seed=seed))
    det = BlinkDetector(params)
    found = [b.t for f in sim.frames() if (b := det.update(f))] + [b.t for b in det.flush()]
    truth = [b.t for b in sim.truth]
    hits = sum(1 for t in truth if any(abs(t - d) < 0.4 for d in found))
    false = sum(1 for d in found if not any(abs(t - d) < 0.4 for t in truth))
    return hits / len(truth), false


def test_default_settings_kept_for_typical_eyes():
    r = C.fit(recording())
    assert r.ok and not r.improved and r.default.hits == 6 and r.default.false == 0
    assert "already work well" in r.message


def test_small_blinker_gets_personal_settings_that_generalise():
    depth = (0.78, 0.84)                 # lids only travel ~20%: defaults miss most blinks
    r = C.fit(recording(depth))
    assert r.ok and r.improved and r.best.hits >= 5 and r.best.false == 0
    assert r.default.hits < r.best.hits
    before, fp0 = recall_and_false(BlinkParams(), depth)
    after, fp1 = recall_and_false(C.params_from(r.overrides), depth)
    print("held-out recall", before, "->", after, "false", fp0, "->", fp1)
    assert after >= before + 0.4 and after >= 0.8          # on a session it never saw
    assert fp1 <= fp0 + 2                                  # without inventing blinks


def test_unusable_recording_is_reported_not_saved():
    r = C.fit([FrameFeatures(t=i / FPS, face=False) for i in range(600)])
    assert not r.ok and not r.overrides and "face" in r.message
    r = C.fit(recording(depth=(0.93, 0.97)))         # blinks invisible to the camera
    assert not r.ok and not r.overrides and "Fix the setup" in r.message
    assert not C.fit([]).ok


def test_overrides_are_sanitised():
    assert C.clean_overrides({"min_prominence": 0.01, "noise_k": 99, "evil": 1,
                              "max_pitch_shift": True, "min_rel_prominence": "x"}) == {
        "min_prominence": 0.12, "noise_k": 6.5}
    assert C.clean_overrides("junk") == {}
    assert C.params_from({"min_prominence": 0.15}).min_prominence == 0.15


def test_session_cues_and_result():
    s = C.Session(background=False)
    states = []
    for f in recording():
        s.feed(f)
        states.append(s.state())
    steps = [st.get("step") for st in states if not st["done"]]
    assert steps[0] == "settle" and "cued" in steps and "still" in steps and "down" in steps
    assert sum(1 for a, b in zip(states, states[1:], strict=False) if b.get("cue") and not a.get("cue")) == 6
    assert any(st.get("look_down") for st in states)
    assert states[-1]["done"] and states[-1]["ok"] and s.frames == []      # recording dropped


def test_app_calibration_flow(tmp_path):
    from blinkwise.app import App
    from blinkwise.config import Settings

    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    app._on_dashboard_action("calibrate")
    frames = recording(depth=(0.78, 0.84))
    app._step(frames[0])
    assert app.calib is not None and app.quiet                 # no pop-ups while calibrating
    app.calib.background = False
    for f in frames[1:]:
        app._step(f)
    app._publish()
    snap = app.snapshot()
    assert snap["calibration"]["done"] and snap["calibration"]["improved"]
    app._on_dashboard_action("calibrate_save")
    app._drain_commands()
    saved = Settings.load().blink_overrides
    assert saved and app.engine.detector.p.min_prominence == saved["min_prominence"]
    assert app.calib is None and not app.quiet
    app._on_dashboard_action("calibrate_reset")
    app._drain_commands()
    assert Settings.load().blink_overrides == {} and app.engine.detector.p == BlinkParams()
    app.history.close()


def test_save_without_a_result_does_nothing(tmp_path):
    from blinkwise.app import App
    from blinkwise.config import Settings

    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    app._on_dashboard_action("calibrate_save")
    app._drain_commands()
    assert app.s.blink_overrides == {}
    app.history.close()


@pytest.mark.parametrize("react", [0.25, 1.0])
def test_slow_or_fast_reactions_still_count(react):
    r = C.fit(recording(react=react))
    assert r.ok and r.default.hits == 6

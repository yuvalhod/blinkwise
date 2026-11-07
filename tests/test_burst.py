"""Burst sampling: camera on 1 minute in every 5, the last pose carried forward."""

import dataclasses
import threading
import time

from blinkwise import app as app_mod
from blinkwise import system
from blinkwise.app import App
from blinkwise.config import Settings
from blinkwise.core.engine import Engine
from blinkwise.core.events import BreakDue, StareCue
from blinkwise.core.simulate import Scenario, Screen, Simulation
from blinkwise.legal import TERMS_VERSION
from blinkwise.ui.menu import build_menu

ON, OFF = 60.0, 240.0


def burst_frames(sim):
    """What the engine sees in burst mode: real frames for 60 s, then 1 Hz carry-forward."""
    last, last_carry = None, -1e9
    for f in sim.frames():
        if (f.t % (ON + OFF)) < ON:
            last = f
            yield f, False
        elif last is not None and f.t - last_carry >= 1.0:
            last_carry = f.t
            yield dataclasses.replace(last, t=f.t, ear_right=0.0, ear_left=0.0, extrapolated=True), True


def test_burst_keeps_breaks_and_screen_time_and_honest_blink_rate():
    sc = Scenario(duration_s=26 * 60, fps=15, blink_rate=12, screens=(Screen(0.0),), seed=5)
    sim = Simulation(sc)
    eng = Engine(Settings(), monitors=1)
    cues_while_resting, breaks, observed = 0, [], 0.0
    for f, resting in burst_frames(sim):
        for ev in eng.step(f):
            if isinstance(ev, StareCue) and resting:
                cues_while_resting += 1
            if isinstance(ev, BreakDue):
                breaks.append(f.t)
            if hasattr(ev, "observed_s"):
                observed += ev.observed_s
    snap = eng.snapshot()
    assert cues_while_resting == 0                    # no stare cues from invented data
    assert breaks and 19 * 60 <= breaks[0] <= 22 * 60  # 20-20-20 still on time
    assert snap["screen_minutes"] >= 24                # screen time extrapolated
    assert observed <= 0.25 * sc.duration_s           # blink stats only from measured minutes
    true_rate = len(sim.truth) / (sc.duration_s / 60)
    measured = eng.stats.window(eng._last_t, 1800).rate
    assert abs(measured - true_rate) / true_rate < 0.3


def test_burst_carries_away_state():
    """Left the desk during the last measured seconds -> resting minutes count as away."""
    sc = Scenario(duration_s=600, fps=15, away=((40.0, 600.0),), seed=2)
    eng = Engine(Settings(), monitors=1)
    for f, _ in burst_frames(Simulation(sc)):
        eng.step(f)
    assert eng.snapshot()["screen_minutes"] < 1.0


def test_app_burst_cycle(tmp_path, monkeypatch):
    """The camera is opened for the on-phase and released for the off-phase."""
    import blinkwise.vision.camera as cam
    import blinkwise.vision.tracker as trk
    from blinkwise.vision.features import FrameFeatures

    monkeypatch.setattr(app_mod, "BURST_ON_S", 0.6)
    monkeypatch.setattr(app_mod, "BURST_OFF_S", 2.4)
    opened, released = [], []

    class Cam:
        def __init__(self, *a, **k):
            opened.append(time.monotonic())
            self.max_fps = 30

        def read(self):
            time.sleep(1 / 30)
            return time.monotonic(), None

        def release(self):
            released.append(time.monotonic())

    class Tracker:
        def __init__(self, *a, **k):
            pass

        def process(self, frame, t):
            return FrameFeatures(t=t, face=True, ear_right=0.3, ear_left=0.3, width_right=30,
                                 width_left=30, yaw=0, pitch=-5, distance_cm=60, luminance=120,
                                 faces=1, face_px=150, vis_right=0.07, vis_left=0.07)

        def close(self):
            pass

    monkeypatch.setattr(cam, "FrameSource", Cam)
    monkeypatch.setattr(trk, "FaceTracker", Tracker)
    monkeypatch.setattr(trk, "ensure_model", lambda d: "model")
    app = App(Settings(sampling="burst", terms_version=TERMS_VERSION), ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1, probe=system.SystemState)
    t = threading.Thread(target=app._worker_main)
    t.start()
    time.sleep(1.5)                       # inside the first off phase
    snap = app.snapshot()
    time.sleep(2.2)                       # into the second on phase
    app.stop.set()
    t.join(3)
    assert app.error is None
    assert len(opened) == 2 and len(released) == 2
    assert snap["camera_resting"] and 1 <= snap["camera_back_in_s"] <= 2
    assert build_menu(snap, blink_cue="subtle", autostart=None)[0].text.startswith(
        "Blinkwise: Camera resting")
    assert app.engine._screen_s > 1.5        # seconds, carried through the rest (not the rounded minutes)
    app.history.close()


def test_calibration_keeps_the_camera_on(tmp_path):
    app = App(Settings(sampling="burst"), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    app._burst_anchor = time.monotonic() - 100      # off phase
    assert app.burst_resting() and not app.camera_wanted()
    app.commands.put("calibrate")
    app._drain_commands()
    assert not app.burst_resting() and app.camera_wanted()
    app._on_settings({"sampling": "continuous"})
    app.calib = None
    assert not app.burst_resting()
    app.history.close()

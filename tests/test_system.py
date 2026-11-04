"""Battery saver, video-call detection and a busy camera."""

import time

import pytest

from blinkwise import system
from blinkwise.app import App
from blinkwise.config import Settings
from blinkwise.ui.menu import build_menu


def test_call_detection_from_process_names():
    assert system.call_app_from_processes(["finder", "zoom.us"]) is None   # Zoom open, no meeting
    assert system.call_app_from_processes(["zoom.us", "cpthost"]) == "Zoom"
    assert system.call_app_from_processes(["facetime"]) == "FaceTime"


def test_probe_combines_signals_and_survives_errors():
    def boom():
        raise RuntimeError("no access")
    s = system.probe(battery=lambda: True, processes=boom, camera_in_use=lambda: True)
    assert s.on_battery is True and s.call == "a video call"
    s = system.probe(battery=lambda: None, processes=lambda: ["cpthost"], camera_in_use=lambda: None)
    assert s.call == "Zoom"
    s = system.probe(battery=lambda: False, processes=lambda: [], camera_in_use=lambda: None)
    assert s.call is None and s.on_battery is False


def test_real_probe_does_not_crash():
    s = system.probe()
    assert s.on_battery in (True, False, None)


def _app(tmp_path, state, **settings):
    st = Settings(**settings)
    app = App(st, demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1, probe=lambda: state)
    app.poll_system()
    return app


def test_battery_saver(tmp_path):
    on_batt = system.SystemState(on_battery=True)
    assert _app(tmp_path, on_batt).fps_cap() == 12
    assert _app(tmp_path, on_batt, battery_saver="off").fps_cap() == 24
    assert _app(tmp_path, system.SystemState(on_battery=False)).fps_cap() == 24
    assert _app(tmp_path, system.SystemState(), battery_saver="always").fps_cap() == 12
    assert _app(tmp_path, on_batt, max_fps=10).fps_cap() == 10        # never raises the cap


def test_call_quiet_mode(tmp_path):
    from blinkwise.core.events import Suggestion
    app = _app(tmp_path, system.SystemState(call="Zoom"), during_calls="quiet")
    warn = Suggestion("too_close", "warn", "t", "m", notify=True)
    assert app.quiet and not app._should_notify(warn) and app.camera_wanted()
    app._publish()
    snap = app.snapshot()
    assert snap["in_call"] == "Zoom" and snap["quiet_for_s"] is None
    assert build_menu(snap, blink_cue="subtle", autostart=None)[0].text == "Blinkwise: In a call - quiet"
    app._probe = lambda: system.SystemState()
    app.poll_system()                                 # call ended: back to normal
    assert not app.quiet and app._should_notify(warn)


def test_call_pause_releases_camera(tmp_path):
    app = _app(tmp_path, system.SystemState(call="Zoom"), during_calls="pause")
    assert not app.camera_wanted() and not app.paused.is_set()
    app._publish()
    assert build_menu(app.snapshot(), blink_cue="subtle",
                      autostart=None)[0].text == "Blinkwise: In a call - camera off"
    off = _app(tmp_path, system.SystemState(call="Zoom"), during_calls="off")
    assert off.camera_wanted() and not off.quiet


def test_settings_validation():
    s = Settings()
    s.apply_ui_changes({"battery_saver": "always", "during_calls": "pause"})
    assert (s.battery_saver, s.during_calls, s.preset) == ("always", "pause", "balanced")
    with pytest.raises(ValueError):
        s.apply_ui_changes({"during_calls": "explode"})


def test_busy_camera_keeps_app_alive(tmp_path, monkeypatch):
    """Opening the camera fails (another app holds it): retry instead of crashing."""
    import blinkwise.vision.camera as cam
    import blinkwise.vision.tracker as trk

    class Busy:
        def __init__(self, *a, **k):
            raise RuntimeError("Could not open camera 0.")

    class Tracker:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

    monkeypatch.setattr(cam, "FrameSource", Busy)
    monkeypatch.setattr(trk, "FaceTracker", Tracker)
    monkeypatch.setattr(trk, "ensure_model", lambda d: "model")
    app = App(Settings(), ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1, probe=system.SystemState)
    import threading
    t = threading.Thread(target=app._worker_main)
    t.start()
    time.sleep(0.6)
    snap = app.snapshot()
    app.stop.set()
    t.join(3)
    assert app.error is None and "Could not open camera" in snap["camera_error"]
    assert build_menu(snap, blink_cue="subtle", autostart=None)[0].text.endswith("retrying")
    app.history.close()


def test_efficient_frame_rate_policy(tmp_path):
    from blinkwise import app as app_mod
    app = _app(tmp_path, system.SystemState(on_battery=False))
    t0 = app._burst_anchor
    assert app.fps_cap(t0 + 10) == 24                       # full-rate minute (completeness)
    assert app.fps_cap(t0 + 100) == app_mod.EFFICIENT_FPS   # the other 4 minutes
    assert app.fps_cap(t0 + 310) == 24
    avg = sum(app.fps_cap(t0 + s) for s in range(300)) / 300
    assert avg < 17                                         # vs 24 before: ~30% fewer frames
    # Nothing to measure -> slow down.
    assert app.activity_fps(0, 0, t0 + 100) == 15
    assert app.activity_fps(0, 8, t0 + 100) == app_mod.EYES_LOST_FPS
    assert app.activity_fps(20, 20, t0 + 100) == app_mod.AWAY_FPS
    assert app.activity_fps(120, 120, t0 + 100) == app_mod.IDLE_FPS
    app.s.performance = "max"
    assert app.fps_cap(t0 + 100) == 24
    app.commands.put("calibrate")
    app._drain_commands()
    app.s.performance = "efficient"
    assert app.fps_cap(t0 + 100) == 24                      # calibration gets every frame


def test_commands_are_handled_while_the_camera_is_off(tmp_path, monkeypatch):
    """Settings changed while paused still apply (they used to wait for the camera)."""
    import threading

    import blinkwise.vision.camera as cam
    import blinkwise.vision.tracker as trk

    class Tracker:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

    monkeypatch.setattr(trk, "FaceTracker", Tracker)
    monkeypatch.setattr(trk, "ensure_model", lambda d: "model")
    monkeypatch.setattr(cam, "FrameSource", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    app = App(Settings(), ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1, probe=system.SystemState)
    app.pause()
    t = threading.Thread(target=app._worker_main)
    t.start()
    app._on_settings({"micro_break_minutes": 30})
    time.sleep(0.6)
    app.stop.set()
    t.join(3)
    assert app.engine.breaks.micro_s == 30 * 60 and app.commands.empty()
    app.history.close()

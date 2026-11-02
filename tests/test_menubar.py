import plistlib

import pytest

from blinkwise.ui import autostart
from blinkwise.ui.icon import STATES, blink_animation, render
from blinkwise.ui.menu import build_menu, icon_state, rate_word
from blinkwise.ui.tray import flatten

PIL = pytest.importorskip("PIL")


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("size", [16, 22, 44, 64])
def test_icon_renders_as_template_image(state, size):
    img = render(state, size)
    assert img.size == (size, size) and img.mode == "RGBA"
    px = list(img.getdata())
    ink = [p for p in px if p[3] > 64]       # ignore faint anti-aliasing fringe
    assert ink, "icon must not be empty"
    assert all(p[:3] == (0, 0, 0) for p in ink)          # pure black + alpha = macOS template
    assert len(ink) < 0.6 * len(px)                      # a glyph, not a filled square


def test_icon_states_are_distinguishable():
    imgs = {s: render(s, 44).tobytes() for s in STATES}
    assert len(set(imgs.values())) == len(STATES)
    assert render("watching", 44, badge=True).tobytes() != imgs["watching"]
    assert len(blink_animation()) >= 4


def test_closed_eye_has_lashes_below_the_lid():
    """The closed eye: ink in the lower part of the icon (lashes hang below the lid)."""
    img = render("watching", 64)
    alpha = img.getchannel("A")
    w, h = img.size
    lower = sum(alpha.getpixel((x, y)) > 0 for x in range(w) for y in range(int(h * 0.55), h))
    assert lower > 20


SNAP = dict(running=True, face=True, paused=False, preset="balanced", blink_rate_5m=8.4,
            seconds_since_blink=4.2,
            next_break_s=725, break_active=None, quality={"level": "good"},
            today={"screen_minutes": 200.0, "device_minutes": 35.0, "multitask_minutes": 22,
                   "breaks_taken": 4})


def test_menu_reads_in_plain_words():
    text = flatten(build_menu(SNAP, blink_cue="menubar", autostart=False))
    assert text[0] == "Blinkwise: Watching your blinks"
    assert "Blinking: 8 a minute, low" in text
    assert "Last blink: 4 s ago" in text
    assert "Next eye break: in 12 min" in text
    assert "Screen time today: 3 h 20 min" in text
    assert "Phone / other device: 35 min, 22 min both at once" in text
    assert "Take a 20-second eye break" in text and "Pause camera >" in text
    assert "Quiet for 1 hour (keep measuring)" in text
    assert "  (x) Balanced" in text and "  ( ) Coach - big prompts, full-screen breaks" in text
    assert "( ) Start at login" in text
    assert text[-1] == "Quit Blinkwise"


def test_menu_when_paused_and_during_break():
    paused = flatten(build_menu({**SNAP, "paused": True, "paused_for_s": 1500}, blink_cue="subtle",
                                autostart=None))
    assert paused[0] == "Blinkwise: Paused - camera off (25 min left)"
    assert "Resume" in paused and not any(t.startswith("Blinking") for t in paused)
    brk = flatten(build_menu({**SNAP, "break_active": "micro"}, blink_cue="subtle", autostart=None))
    assert "Skip this break" in brk and any("Eye break: now" in t for t in brk)


def test_menu_flags_poor_tracking_and_icon_states():
    poor = flatten(build_menu({**SNAP, "quality": {"level": "poor"}}, blink_cue="off", autostart=None))
    assert poor[0] == "Blinkwise: Can't see your eyes clearly"
    assert icon_state(SNAP) == ("watching", False)
    assert icon_state({**SNAP, "break_active": "micro"}) == ("watching", True)
    assert icon_state({**SNAP, "paused": True}) == ("paused", False)
    assert icon_state({**SNAP, "face": False}) == ("away", False)
    assert rate_word(None) == "measuring..." and rate_word(17) == "17 a minute, healthy"


@pytest.mark.parametrize("platform", ["darwin", "win32", "linux"])
def test_autostart_roundtrip(platform, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    assert not autostart.is_enabled(platform)
    p = autostart.enable(platform)
    assert p.exists() and str(p).startswith(str(tmp_path))
    if platform == "darwin":
        plist = plistlib.loads(p.read_bytes())
        assert plist["RunAtLoad"] is True and plist["ProgramArguments"][-2:] == ["blinkwise", "run"]
    else:
        assert "blinkwise" in p.read_text()
    assert autostart.toggle(platform) is False and not p.exists()


def test_menu_actions_drive_the_app(tmp_path):
    from blinkwise.app import App
    from blinkwise.config import Settings

    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    app._on_tray_action("pause:30")
    assert app.paused.is_set() and 1790 < app._paused_until - __import__("time").monotonic() <= 1800
    app._publish()
    snap = app.snapshot()
    assert snap["paused"] and 1790 <= snap["paused_for_s"] <= 1800
    app._paused_until = 0.001                       # pretend 30 minutes passed
    app._publish()
    assert not app.paused.is_set()                  # auto-resumed
    app._on_tray_action("pause:0")
    assert app.paused.is_set() and app._paused_until is None
    app._on_tray_action("resume")
    assert not app.paused.is_set()
    app._on_tray_action("cue:menubar")
    assert Settings.load().blink_cue == "menubar"
    app._on_tray_action("break_now")
    assert app.commands.get_nowait() == "break_now"
    app._on_tray_action("quit")
    assert app.stop.is_set()
    app.history.close()


def test_menu_quiet_and_custom_style():
    quiet = flatten(build_menu({**SNAP, "quiet_for_s": 2400}, blink_cue="subtle", autostart=None))
    assert quiet[0] == "Blinkwise: Quiet - measuring, no pop-ups (40 min left)"
    assert "End quiet time (40 min left)" in quiet
    custom = flatten(build_menu({**SNAP, "preset": "custom"}, blink_cue="subtle", autostart=None))
    assert "  Custom (set in the dashboard)" in custom


def test_quiet_and_presets_from_the_menu(tmp_path):
    from blinkwise.app import App
    from blinkwise.config import Settings
    from blinkwise.core.events import Suggestion

    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    warn = Suggestion("too_close", "warn", "t", "m", notify=True)
    info = Suggestion("multi_screen", "info", "t", "m", notify=True)
    assert app._should_notify(warn) and not app._should_notify(info)    # "important" default
    app._on_tray_action("quiet:60")
    assert app.quiet and not app._should_notify(warn)
    app._on_tray_action("quiet:0")
    assert not app.quiet
    app._on_tray_action("preset:gentle")
    assert app.s.preset == "gentle" and not app._should_notify(warn)    # gentle: no pop-ups
    assert Settings.load().preset == "gentle"
    app._on_tray_action("preset:coach")
    assert app._should_notify(info)                                    # coach: all
    assert app.commands.get_nowait() == "settings"
    app.history.close()

"""Update check: daily, anonymous, never fatal."""

from blinkwise import updates
from blinkwise.app import App
from blinkwise.config import Settings
from blinkwise.ui.menu import build_menu


def test_version_compare():
    assert updates.is_newer("0.2.0", "0.1.0")
    assert updates.is_newer("v0.1.1", "0.1")
    assert not updates.is_newer("0.1.0", "0.1.0")
    assert not updates.is_newer("0.1.0", "0.10.0")
    assert not updates.is_newer("nightly", "0.1.0")
    assert updates.parse_version("1.2.3-beta") == (1, 2, 3)


def test_checks_once_a_day_and_remembers(tmp_path):
    calls, now = [], [1000.0]

    def fetch():
        calls.append(1)
        return {"version": "9.0.0", "url": "https://github.com/yuvalhod/blinkwise/releases/tag/v9.0.0"}

    c = updates.UpdateChecker(tmp_path / "u.json", fetch=fetch, clock=lambda: now[0])
    assert c.maybe_check()["version"] == "9.0.0"
    c.maybe_check()
    assert len(calls) == 1                                    # not again the same day
    c2 = updates.UpdateChecker(tmp_path / "u.json", fetch=fetch, clock=lambda: now[0])
    assert c2.maybe_check()["version"] == "9.0.0" and len(calls) == 1   # survives restart
    now[0] += updates.CHECK_EVERY_S + 1
    c2.maybe_check()
    assert len(calls) == 2


def test_offline_or_garbage_is_harmless(tmp_path):
    def offline():
        raise OSError("no network")
    c = updates.UpdateChecker(tmp_path / "u.json", fetch=offline, clock=lambda: 5.0)
    assert c.maybe_check() is None and c.state["next_check"] == 5.0 + updates.RETRY_AFTER_ERROR_S
    (tmp_path / "bad.json").write_text("{not json")
    c = updates.UpdateChecker(tmp_path / "bad.json", fetch=lambda: None, clock=lambda: 5.0)
    assert c.maybe_check() is None
    old = updates.UpdateChecker(tmp_path / "o.json", fetch=lambda: {"version": "0.0.1", "url": "x"})
    assert old.maybe_check() is None                          # older than us: nothing shown


def test_app_menu_shows_update_and_respects_opt_out(tmp_path, monkeypatch):
    info = {"version": "9.0.0", "url": "https://github.com/yuvalhod/blinkwise/releases/tag/v9.0.0"}
    monkeypatch.setattr(updates, "fetch_latest", lambda: info)
    monkeypatch.setattr(updates.UpdateChecker.__init__, "__defaults__",
                        (lambda: info, updates.time.time))
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    app.check_updates()
    app._publish()
    texts = [i.text for i in build_menu(app.snapshot(), blink_cue="subtle", autostart=None)]
    assert "Update available: 9.0.0..." in texts
    app._on_tray_action("update")
    assert opened == [info["url"]]
    app.s.check_updates = False
    app.check_updates()
    app._publish()
    assert app.snapshot()["update"] is None
    app.history.close()

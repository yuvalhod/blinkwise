"""Privacy Policy, Terms of Use and the consent gate before the camera turns on."""

import json
import urllib.request

import pytest

from blinkwise import legal
from blinkwise.app import App
from blinkwise.config import Settings
from blinkwise.ui.menu import build_menu


def test_documents_ship_and_render_safely():
    for name in ("privacy", "terms"):
        md = legal.text(name)
        assert legal.TERMS_VERSION in md
        html = legal.page(name)
        assert "<h1>" in html and "<script" not in html.lower()
    assert "not a medical device" in legal.text("terms").lower()
    assert "never saved" in legal.text("privacy").lower()
    assert "&lt;script&gt;" in legal.to_html("<script>alert(1)</script>")       # escaped
    t = legal.to_html("| a | b |\\n|---|---|\\n| **x** | `y` |".replace("\\\\n", "\\n"))
    assert "<table>" in t and "<b>x</b>" in t and "<code>y</code>" in t


def test_camera_stays_off_until_terms_are_accepted(tmp_path):
    app = App(Settings(), ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    assert app.consent_needed and not app.camera_wanted()
    app._publish()
    snap = app.snapshot()
    menu = build_menu(snap, blink_cue="subtle", autostart=None)
    assert menu[0].text == "Blinkwise: Camera off until you review and start"
    assert any(i.action == "setup" and i.text.startswith("Review") for i in menu)
    with pytest.raises(ValueError):
        app._on_settings({"terms_version": "1999-01-01"})          # only the current version
    app._on_settings({"terms_version": legal.TERMS_VERSION})
    assert not app.consent_needed and app.camera_wanted()
    assert Settings.load().terms_version == legal.TERMS_VERSION    # once, then never again
    app.history.close()


def test_accepting_works_even_with_a_parent_pin(tmp_path):
    from blinkwise.family.client import hash_pin
    app = App(Settings(parent_pin=hash_pin("1234")), ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    app._on_settings({"terms_version": legal.TERMS_VERSION})
    assert not app.consent_needed
    app.history.close()


def test_demo_needs_no_consent(tmp_path):
    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    assert not app.consent_needed
    app.history.close()


def test_dashboard_serves_legal_pages_and_setup_has_the_step(tmp_path):
    from blinkwise.ui.dashboard import DashboardServer
    srv = DashboardServer(0)
    base = srv.start()
    try:
        for p in ("privacy", "terms"):
            body = urllib.request.urlopen(base + p).read().decode()
            assert "Blinkwise" in body and legal.TERMS_VERSION in body
        setup = urllib.request.urlopen(base + "setup").read().decode()
        assert 'id="step0"' in setup and legal.TERMS_VERSION in setup and "__TERMS_VERSION__" not in setup
        assert "not a medical device" in setup.lower()
        page = urllib.request.urlopen(base).read().decode()
        assert 'href="/privacy"' in page and 'href="/terms"' in page
        assert json.loads(urllib.request.urlopen(base + "api/live").read())["running"] is False
    finally:
        srv.stop()

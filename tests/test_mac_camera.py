"""macOS camera permission: asked through AVFoundation, and reported clearly."""

import sys
import types

import pytest

from blinkwise import mac_camera
from blinkwise.ui.menu import build_menu


class FakeAV:
    """Stand-in for PyObjC's AVFoundation: status 0 until the prompt is answered."""

    def __init__(self, answer):
        self.state, self.answer, self.asked = 0, answer, 0
        av = self

        class Device:
            @staticmethod
            def authorizationStatusForMediaType_(media):
                return av.state

            @staticmethod
            def requestAccessForMediaType_completionHandler_(media, handler):
                av.asked += 1
                av.state = 3 if av.answer else 2
                handler(av.answer)
        self.module = types.SimpleNamespace(AVCaptureDevice=Device, AVMediaTypeVideo="vide")


@pytest.fixture
def mac(monkeypatch):
    def install(answer):
        fake = FakeAV(answer)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setitem(sys.modules, "AVFoundation", fake.module)
        return fake
    return install


def test_prompt_is_shown_once_and_answer_read(mac):
    fake = mac(True)
    assert mac_camera.status() == "not_determined"
    assert mac_camera.request() == "authorized" and fake.asked == 1
    assert mac_camera.request() == "authorized" and fake.asked == 1      # not asked again


def test_unknown_off_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert mac_camera.status() is None and mac_camera.request() is None


def test_app_waits_while_denied_and_says_why(mac, tmp_path):
    from blinkwise.app import App
    from blinkwise.config import Settings
    from blinkwise.legal import TERMS_VERSION

    fake = mac(False)
    app = App(Settings(terms_version=TERMS_VERSION), ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    assert app._camera_permitted() is False and fake.asked == 1
    app._publish()
    snap = app.snapshot()
    assert snap["camera_permission"] == "denied"
    menu = build_menu(snap, blink_cue="subtle", autostart=None)
    assert menu[0].text == "Blinkwise: Camera blocked - allow it in System Settings"
    assert any(i.action == "camera_settings" for i in menu)
    fake.state = 3                                      # allowed later in System Settings
    assert app._camera_permitted() is True and app.camera_permission == "authorized"
    app.history.close()

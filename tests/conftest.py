import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never touch the real user's settings/history during tests."""
    monkeypatch.setenv("BLINKWISE_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture(autouse=True)
def no_real_camera_permissions(monkeypatch):
    """Never consult the real machine's macOS privacy settings (CI runners deny the
    camera); tests that need a specific answer install their own fake AVFoundation."""
    from blinkwise import mac_camera
    monkeypatch.setattr(mac_camera, "_av", lambda: None)

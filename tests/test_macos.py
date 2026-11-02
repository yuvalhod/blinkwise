import os
import plistlib

import pytest

pytest.importorskip("PIL")
from blinkwise import macos  # noqa: E402
from blinkwise.cli import main  # noqa: E402


def test_bundle_structure(tmp_path):
    app = macos.build_bundle(tmp_path / "Blinkwise.app", python="/opt/py env/bin/python3")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "Blinkwise" and info["CFBundleIdentifier"] == "com.blinkwise.app"
    assert info["LSUIElement"] is True                          # menu-bar app, no Dock icon
    assert "never stored" in info["NSCameraUsageDescription"]  # required for camera access
    exe = app / "Contents/MacOS/Blinkwise"
    assert os.access(exe, os.X_OK)
    script = exe.read_text()
    assert "'/opt/py env/bin/python3' -m blinkwise run --app" in script   # quoted path with space
    icns = app / "Contents/Resources/Blinkwise.icns"
    assert icns.read_bytes()[:4] == b"icns" and icns.stat().st_size > 10_000


def test_install_and_uninstall_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(macos, "default_location", lambda: tmp_path / "Applications/Blinkwise.app")
    assert main(["install-app"]) == 0
    assert (tmp_path / "Applications/Blinkwise.app/Contents/Info.plist").exists()
    assert main(["install-app"]) == 0                          # reinstall over an existing one
    assert main(["uninstall-app"]) == 0
    assert not (tmp_path / "Applications/Blinkwise.app").exists()
    assert "Removed" in capsys.readouterr().out

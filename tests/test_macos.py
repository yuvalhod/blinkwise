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


def test_launcher_keeps_blinkwise_running():
    from blinkwise.macos import launcher_script
    s = launcher_script("/Users/me/blinkwise/.venv/bin/python")
    assert "while true" in s and "--menubar-only" in s
    assert '[ "$code" -eq 0 ] && exit 0' in s          # Quit from the menu stops it
    assert "trap" in s and "TERM" in s                  # logging out stops it
    assert '[ "$fails" -ge 5 ] && exit 1' in s          # no endless crash loop


def test_only_one_copy_runs(tmp_path, monkeypatch):
    from blinkwise import cli
    monkeypatch.setenv("BLINKWISE_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_LOCK", None)
    first = cli._single_instance()
    assert first is not None
    assert cli._single_instance() is None              # a second copy backs off
    first.close()
    monkeypatch.setattr(cli, "_LOCK", None)
    assert cli._single_instance() is not None          # free again once the first exits

import pytest

from blinkwise.cli import main
from blinkwise.config import Settings
from blinkwise.ui.notify import build_command


def test_settings_roundtrip_and_coercion():
    s = Settings.load()
    assert s.stare_seconds == 10.0
    s.update(stare_seconds="7.5", adaptive_breaks="false", camera="1", dashboard_port="9000")
    s.save()
    t = Settings.load()
    assert (t.stare_seconds, t.adaptive_breaks, t.camera, t.dashboard_port) == (7.5, False, 1, 9000)
    with pytest.raises(KeyError):
        s.update(nope=1)


def test_corrupt_settings_fall_back_to_defaults():
    p = Settings.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert Settings.load() == Settings()


def test_cli_config_and_science(capsys):
    assert main(["config", "stare_seconds=6"]) == 0
    assert Settings.load().stare_seconds == 6
    assert main(["config", "bogus=1"]) == 2
    assert main(["science"]) == 0
    assert "Portello" in capsys.readouterr().out
    assert main(["report"]) == 0


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_notification_text_is_escaped(platform):
    evil = 'He said "hi" \' & $(rm -rf ~) `x`'
    cmd = build_command(evil, evil, platform)
    assert isinstance(cmd, list) and len(cmd) >= 3          # argv list, never a shell string
    script = cmd[-1]
    if platform == "darwin":
        assert '\\"hi\\"' in script
    else:
        assert "''" in script                                # PowerShell single-quote doubling


def test_linux_notification_passes_text_as_arguments():
    cmd = build_command("t", "m; reboot", "linux-test")
    assert cmd[-2:] == ["t", "m; reboot"]

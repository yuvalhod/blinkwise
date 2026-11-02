from blinkwise.core.simulate import _lid_profile
from blinkwise.selftest import run_selftest, schedule, total_seconds
from blinkwise.vision.features import FrameFeatures


def synthetic(blink_offsets, fps=30.0, noise=None, turn=True):
    """Frames following the self-test script; blinks at the given offsets (seconds)."""
    import random
    rng = random.Random(3)
    plan = {ph.key: (a, b) for ph, a, b in schedule()}
    out = []
    n = int(total_seconds() * fps) + 5
    for i in range(n):
        t = i / fps
        lid = min([1.0] + [_lid_profile(t - b, 0.1, False) for b in blink_offsets])
        a, b = plan["turn"]
        yaw = 30.0 if (turn and a + 1 < t < b - 2) else 0.0
        e = 0.3 * lid + (rng.gauss(0, noise) if noise else 0.0)
        out.append(FrameFeatures(t=100 + t, face=True, ear_right=e, ear_left=e, width_right=30,
                                 width_left=30, yaw=yaw, face_px=150, luminance=120, distance_cm=60))
    return out


def blink_times():
    a, b = {ph.key: (a, b) for ph, a, b in schedule()}["blink"]
    return [a + 1.0 + i * 1.3 for i in range(5)]


def test_selftest_passes_for_a_good_camera():
    prompts = []
    rep = run_selftest(synthetic(blink_times()), on_prompt=lambda ph, i, n: prompts.append(ph.key))
    assert prompts == ["settle", "blink", "still", "turn"]
    assert rep.blinks_in_blink_phase == 5 and rep.blinks_in_still_phase == 0
    assert rep.passed, rep.lines()
    assert 55 < rep.distance_cm < 65


def test_selftest_flags_missed_blinks_phantoms_and_no_head_turn():
    still_a, _ = {ph.key: (a, b) for ph, a, b in schedule()}["still"]
    frames = synthetic(blink_times()[:2] + [still_a + 1, still_a + 3], turn=False)
    rep = run_selftest(frames)
    failed = {c.name for c in rep.checks if not c.ok}
    assert {"Detects your blinks", "No phantom blinks", "Head tracking"} <= failed
    assert not rep.passed
    assert any("->" in line for line in rep.lines())


def test_selftest_low_fps_is_reported():
    rep = run_selftest(synthetic(blink_times(), fps=12))
    fr = next(c for c in rep.checks if c.name == "Frame rate")
    assert not fr.ok and "12 fps" in fr.detail

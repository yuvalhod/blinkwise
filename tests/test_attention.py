from blinkwise.core.simulate import Scenario, Screen, Simulation
from blinkwise.vision.attention import AttentionTracker


def _feed(sc):
    """Returns tracker, last t and the true screen-crossing times (yaw passing the midpoint)."""
    at = AttentionTracker()
    last, crossings, side = None, [], None
    at.left_time = []
    mid = (min(x.yaw for x in sc.screens) + max(x.yaw for x in sc.screens)) / 2
    for f in Simulation(sc).frames():
        dt = 0 if last is None else f.t - last
        last = f.t
        at.update(f.t, dt, f.face, f.yaw, f.pitch)
        s = f.yaw > mid
        at.left_time.append((f.t, not s))
        if side is not None and s != side:
            crossings.append(f.t)
        side = s
    return at, last, crossings


def test_two_screens_found_with_correct_angles_split_and_switches():
    at, t, crossings = _feed(Scenario(duration_s=900, fps=10, dwell_s=20, seed=3,
                                      screens=(Screen(-5, share=.5), Screen(30, share=.5))))
    z = at.zones
    assert len(z) == 2
    assert abs(z[0].center_yaw + 5) < 3 and abs(z[1].center_yaw - 30) < 3
    recent = [left for tt, left in at.left_time if t - tt <= at.horizon_s]
    true_share = sum(recent) / len(recent)
    assert abs(z[0].share - true_share) < 0.05
    true_rate = sum(1 for c in crossings if t - c <= 300) / 5.0
    assert true_rate > 0.5
    assert abs(at.switches_per_min(t) - true_rate) <= 0.4


def test_single_screen_is_one_zone():
    at, _, _ = _feed(Scenario(duration_s=300, fps=10, seed=3))
    assert len(at.zones) == 1


def test_three_screens():
    at, _, _ = _feed(Scenario(duration_s=1200, fps=10, dwell_s=15, seed=9,
                           screens=(Screen(-35, share=.3), Screen(0, share=.4), Screen(35, share=.3))))
    assert len(at.zones) == 3


def test_looking_away_is_not_a_screen():
    at = AttentionTracker()
    for i in range(600):
        at.update(i * 0.1, 0.1, True, 80.0, 0.0)
    assert at.zones == [] and not at.attending(True, 80.0)

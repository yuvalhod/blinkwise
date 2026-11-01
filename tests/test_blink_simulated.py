from helpers import match, run_detector

from blinkwise.core.simulate import Scenario, Screen, Simulation
from blinkwise.vision.blink import BlinkDetector
from blinkwise.vision.features import FrameFeatures


def test_clean_30fps_detection_and_completeness():
    truth, found = run_detector(Scenario(duration_s=300, incomplete_frac=0.35, seed=1))
    pairs, fps, misses = match(truth, found)
    assert len(truth) > 25
    assert not fps and not misses
    assert all(b.complete == t.complete for t, b in pairs)


def test_long_blinks_detected_once_and_flagged():
    truth, found = run_detector(Scenario(duration_s=300, long_frac=0.3, seed=2))
    pairs, fps, misses = match(truth, found)
    assert not fps and not misses
    for t, b in pairs:
        assert b.long == t.long


def test_keyboard_glances_and_two_screens():
    sc = Scenario(duration_s=600, screens=(Screen(-5, -4, .6), Screen(32, -3, .4)),
                  keyboard_glances_per_min=3, incomplete_frac=0.3, seed=4)
    truth, found = run_detector(sc)
    pairs, fps, misses = match(truth, found)
    assert len(pairs) / len(truth) >= 0.97
    assert len(fps) <= 1   # ~30 glances down; at most one may be mistaken for a blink


def test_low_fps_detects_but_does_not_judge_completeness():
    truth, found = run_detector(Scenario(duration_s=300, fps=12, seed=5))
    pairs, fps, misses = match(truth, found)
    assert len(pairs) / len(truth) >= 0.95 and not fps
    assert all(b.complete is None for b in found)


def test_leaving_the_desk_resets_cleanly():
    truth, found = run_detector(Scenario(duration_s=240, away=((60, 120),), seed=6))
    pairs, fps, misses = match(truth, found)
    assert not fps and len(misses) <= 1
    assert all(not (60 <= b.t <= 120) for b in found)


def test_extreme_yaw_frames_are_ignored():
    det = BlinkDetector()
    for i in range(200):
        f = FrameFeatures(t=i / 30, face=True, ear_right=0.3 if i % 7 else 0.02,
                          ear_left=0.3 if i % 7 else 0.02, width_right=20, width_left=20, yaw=70)
        assert det.update(f) is None
    assert det.openness is None


def test_noisy_camera_does_not_hallucinate_blinks():
    """8% per-frame EAR noise (dim room / cheap webcam). Before noise adaptation this
    produced ~440 false blinks per hour; the detector must back off instead."""
    sc = Scenario(duration_s=600, incomplete_frac=0.3, ear_noise=0.024, pose_noise_deg=1.5,
                  keyboard_glances_per_min=2, seed=12)
    truth, found = run_detector(sc)
    pairs, fps, misses = match(truth, found)
    assert len(fps) <= 2
    assert len(pairs) / len(truth) >= 0.9


def test_flush_returns_blinks_at_end_of_stream():
    sc = Scenario(duration_s=20, blink_rate=1, seed=1)
    sim = Simulation(sc)
    frames = list(sim.frames())
    # Put a blink in the last 0.2 s, where the look-ahead window can't complete.
    from blinkwise.core.simulate import TruthBlink, _lid_profile
    t_end = frames[-1].t
    tb = t_end - 0.2
    for f in frames:
        lid = _lid_profile(f.t - tb, 0.1, False)
        f.ear_right *= lid
        f.ear_left *= lid
    det = BlinkDetector()
    found = [b for f in frames if (b := det.update(f))]
    assert not any(abs(b.t - tb) < 0.15 for b in found)
    tail = det.flush()
    assert any(abs(b.t - tb) < 0.15 for b in tail)
    assert TruthBlink  # imported for readability of the scenario


def test_two_blinks_before_face_loss_are_both_reported():
    det = BlinkDetector()
    out = []
    for i in range(int(4 * 30)):
        t = i / 30
        lid = min(_lid(t - 2.5), _lid(t - 3.3))
        out.append(det.update(FrameFeatures(t=t, face=True, ear_right=.3 * lid, ear_left=.3 * lid,
                                            width_right=30, width_left=30)))
    out.append(det.update(FrameFeatures(t=4.0, face=False)))
    out.append(det.update(FrameFeatures(t=4.1, face=False)))
    assert len([b for b in out if b is not None]) == 2


def _lid(dt):
    from blinkwise.core.simulate import _lid_profile
    return _lid_profile(dt, 0.1, False)

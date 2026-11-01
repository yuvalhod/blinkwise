from helpers import match, run_detector

from blinkwise.core.simulate import Scenario, Screen
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

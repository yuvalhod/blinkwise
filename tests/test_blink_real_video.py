"""Regression test against hand-labelled real webcam footage (tests/data).

The features were extracted with MediaPipe from Intel's public sample video
(scripts/extract_features.py), so this runs in milliseconds without a model.
"""
import json
from pathlib import Path

import pytest

from blinkwise.vision.evaluate import detect_frames, load_features, score

DATA = Path(__file__).parent / "data"



@pytest.mark.parametrize("name,min_recall", [
    # Development set (parameters were chosen here). Current: P 1.00, R 0.94; misses are the
    # warm-up frame and a slow blink during a 26-degree head nod.
    ("intel_head_pose", 0.90),
    # Held-out set, labelled after parameters were frozen. Current: P 1.00, R 0.96; the miss
    # is a blink during a fast head turn that leaves the trackable range mid-blink.
    ("intel_head_pose_male", 0.90),
])
def test_detector_accuracy_on_labelled_video(name, min_recall):
    fps, frames = load_features(DATA / f"{name}_features.json")
    labels = json.loads((DATA / f"{name}_labels.json").read_text())
    s = score(detect_frames(frames, fps), labels)
    assert s.precision >= 0.95, s.false_positive_frames
    assert s.recall >= min_recall, s.missed_frames


def test_partial_blink_is_detected():
    """Frame 484 of the male video: the left lid closes ~1/3, the right barely moves."""
    fps, frames = load_features(DATA / "intel_head_pose_male_features.json")
    assert any(abs(d - 484) <= 2 for d in detect_frames(frames, fps))


def test_looking_down_is_not_a_blink():
    """Frames 655-748: the subject looks down for ~8 s (EAR halves). At most the real
    blink at the start of the glance (660) may be reported."""
    fps, frames = load_features(DATA / "intel_head_pose_features.json")
    found = [f for f in detect_frames(frames, fps) if 665 <= f <= 745]
    assert found == []


def test_hidden_eyes_never_become_phantom_blinks():
    """Real video with synthetic sunglasses: MediaPipe still finds the face and *guesses*
    eyelids. Before the pixel-level visibility check this produced 11 'blinks', mostly fake.
    Now detection pauses, and the engine reports poor tracking instead of a wrong blink rate."""
    from blinkwise.config import Settings
    from blinkwise.core.engine import Engine
    from blinkwise.vision.blink import BlinkDetector

    fps, frames = load_features(DATA / "intel_head_pose_male_sunglasses_features.json")
    assert sum(f.face for f in frames) / len(frames) > 0.85        # face IS found
    det = BlinkDetector()
    hidden = 0
    blinks = []
    for f in frames:
        b = det.update(f)
        hidden += det.eyes_hidden
        if b:
            blinks.append(b)
    blinks += det.flush()
    assert len(blinks) <= 2
    assert hidden / len(frames) > 0.6

    eng = Engine(Settings(), monitors=1)
    for f in frames:
        eng.step(f)
    snap = eng.snapshot()
    assert snap["quality"]["level"] == "poor"
    assert any("can't see your eyes" in r for r in snap["quality"]["reasons"])

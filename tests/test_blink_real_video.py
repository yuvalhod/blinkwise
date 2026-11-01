"""Regression test against hand-labelled real webcam footage (tests/data).

The features were extracted with MediaPipe from Intel's public sample video
(scripts/extract_features.py), so this runs in milliseconds without a model.
"""
import json
from pathlib import Path

from blinkwise.vision.evaluate import detect_frames, load_features, score

DATA = Path(__file__).parent / "data"


def test_detector_accuracy_on_labelled_video():
    fps, frames = load_features(DATA / "intel_head_pose_features.json")
    labels = json.loads((DATA / "intel_head_pose_labels.json").read_text())
    s = score(detect_frames(frames, fps), labels)
    # Current: precision 1.00, recall 0.90 (misses: warm-up frame 3, a slow blink during
    # a 26-degree head nod, and a blink in the final 0.45 s of the clip).
    assert s.precision >= 0.95, s.false_positive_frames
    assert s.recall >= 0.85, s.missed_frames


def test_looking_down_is_not_a_blink():
    """Frames 655-748: the subject looks down for ~8 s (EAR halves). At most the real
    blink at the start of the glance (660) may be reported."""
    fps, frames = load_features(DATA / "intel_head_pose_features.json")
    found = [f for f in detect_frames(frames, fps) if 665 <= f <= 745]
    assert found == []

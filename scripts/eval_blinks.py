"""Evaluate the blink detector on the labelled fixture: python scripts/eval_blinks.py"""
import json
from pathlib import Path

from blinkwise.vision.evaluate import detect_frames, load_features, score

root = Path(__file__).resolve().parent.parent / "tests" / "data"
fps, frames = load_features(root / "intel_head_pose_features.json")
labels = json.loads((root / "intel_head_pose_labels.json").read_text())
s = score(detect_frames(frames, fps), labels)
print(f"precision={s.precision:.2f} recall={s.recall:.2f} F1={s.f1:.2f}  (tp={s.tp} fp={s.fp} fn={s.fn})")
print("false positives at frames:", s.false_positive_frames)
print("missed blinks at frames:  ", s.missed_frames)

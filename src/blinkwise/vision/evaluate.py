"""Score the blink detector against hand-labelled ground truth.

Matching: a detection matches a labelled blink if its peak frame is within
`tolerance` frames; each label can be matched once. Detections inside
"excluded" or "ambiguous" ranges are ignored (neither TP nor FP), as are
labels inside excluded ranges.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .blink import BlinkDetector, BlinkParams
from .features import FrameFeatures


@dataclass
class Score:
    tp: int
    fp: int
    fn: int
    false_positive_frames: List[int]
    missed_frames: List[int]

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def load_features(path: Path) -> Tuple[float, List[FrameFeatures]]:
    raw = json.loads(Path(path).read_text())
    return raw["fps"], [FrameFeatures(**fr) for fr in raw["frames"]]


def detect_frames(frames: Sequence[FrameFeatures], fps: float,
                  params: Optional[BlinkParams] = None) -> List[int]:
    det = BlinkDetector(params)
    out = []
    for f in frames:
        b = det.update(f)
        if b is not None:
            out.append(int(round(b.t * fps)))
    return out


def score(detected: Sequence[int], labels: dict, tolerance: int = 3) -> Score:
    def inside(i: int, ranges) -> bool:
        return any(a <= i <= b for a, b in ranges)

    ignore = labels.get("excluded", []) + labels.get("ambiguous", [])
    truth = [b for b in labels["blinks"] if not inside(b, labels.get("excluded", []))]
    unmatched = list(truth)
    tp, fps_ = 0, []
    for d in detected:
        best = min(unmatched, key=lambda g: abs(g - d), default=None)
        if best is not None and abs(best - d) <= tolerance:
            unmatched.remove(best)
            tp += 1
        elif not inside(d, ignore):
            fps_.append(d)
    return Score(tp=tp, fp=len(fps_), fn=len(unmatched),
                 false_positive_frames=fps_, missed_frames=unmatched)

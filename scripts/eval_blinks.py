"""Blink-detector benchmark: real labelled video + simulated stress tests.

    python scripts/eval_blinks.py          # full report
    python scripts/eval_blinks.py --quick  # real video only

Real sets (tests/data):
  intel_head_pose       development set (parameters were tuned here)
  intel_head_pose_male  held-out set (labelled after parameters were frozen)

Simulated sets use exact ground truth at 30 fps, so they also score
complete-vs-partial classification and robustness to sensor noise.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from helpers import match, run_detector  # noqa: E402

from blinkwise.core.simulate import Scenario, Screen  # noqa: E402
from blinkwise.vision.evaluate import detect_frames, load_features, score  # noqa: E402

REAL = [("intel_head_pose", "dev"), ("intel_head_pose_male", "held-out")]
SIMS = {
    "clean, 30 fps": dict(),
    "noisy webcam (2x noise)": dict(ear_noise=0.016, pose_noise_deg=1.5),
    "very noisy (3x noise)": dict(ear_noise=0.024, pose_noise_deg=1.5),
    "low fps (12)": dict(fps=12),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    data = ROOT / "tests" / "data"
    print("Real video (12 fps, hand-labelled)")
    for name, split in REAL:
        fps, frames = load_features(data / f"{name}_features.json")
        labels = json.loads((data / f"{name}_labels.json").read_text())
        s = score(detect_frames(frames, fps), labels)
        print(f"  {name:<22} {split:<9} precision {s.precision:.2f}  recall {s.recall:.2f}  "
              f"F1 {s.f1:.2f}  (tp={s.tp} fp={s.fp} fn={s.fn})  missed={s.missed_frames}")
    if args.quick:
        return 0
    print("\nSimulated users (10 min x 6 seeds, two screens, 3 keyboard glances/min, "
          "30% partial, 3% long blinks)")
    for title, kw in SIMS.items():
        tp = n = fp = ok = judged = 0
        for seed in range(6):
            base = dict(duration_s=600, screens=(Screen(-5, -4, .6), Screen(32, -3, .4)),
                        keyboard_glances_per_min=3, incomplete_frac=0.3, long_frac=0.03, seed=seed)
            base.update(kw)
            truth, found = run_detector(Scenario(**base))
            pairs, fps_, _ = match(truth, found)
            tp, n, fp = tp + len(pairs), n + len(truth), fp + len(fps_)
            for t, b in pairs:
                if b.complete is not None:
                    judged += 1
                    ok += b.complete == t.complete
        comp = f"{ok / judged:.3f}" if judged else "n/a (<20 fps)"
        print(f"  {title:<26} recall {tp / n:.3f}  false blinks/hour {fp / (6 * 600 / 3600):.1f}  "
              f"complete-vs-partial accuracy {comp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

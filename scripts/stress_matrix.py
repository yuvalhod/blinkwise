"""When does Blinkwise work, and when does it fail? Real-pixel stress test.

Runs the full pipeline (MediaPipe -> features -> blink detector -> quality grade)
on the held-out labelled video under controlled degradations, and reports
precision/recall plus what the app would tell the user.

    python scripts/stress_matrix.py VIDEO.mp4 [--labels tests/data/intel_head_pose_male_labels.json]

The video is Intel's public head-pose sample (see tests/data/*_labels.json for
the source URL); it isn't committed to the repo.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

from blinkwise.config import data_dir
from blinkwise.vision.blink import BlinkDetector
from blinkwise.vision.evaluate import score
from blinkwise.vision.quality import assess
from blinkwise.vision.tracker import FaceTracker, ensure_model

ROOT = Path(__file__).resolve().parent.parent
EYES = ([33, 133, 159, 145, 160, 144, 158, 153], [263, 362, 386, 374, 385, 380, 387, 373])


def shrink(f, s):
    """Sit farther away: the face covers fewer pixels in a full-size frame."""
    h, w = f.shape[:2]
    small = cv2.resize(f, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    out = np.full_like(f, int(np.median(f)))
    y, x = (h - small.shape[0]) // 2, (w - small.shape[1]) // 2
    out[y:y + small.shape[0], x:x + small.shape[1]] = small
    return out


def scale(f, s):
    h, w = f.shape[:2]
    return cv2.resize(cv2.resize(f, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA), (w, h))


def dim(f, rng, k=0.22, noise=6):
    return np.clip(f.astype(np.float32) * k + rng.normal(0, noise, f.shape), 0, 255).astype(np.uint8)


def backlit(f, rng):
    """Bright window behind: face underexposed relative to a blown-out background."""
    g = f.astype(np.float32)
    lum = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = (lum > np.percentile(lum, 55)).astype(np.float32)[..., None]
    out = g * 0.35 * (1 - bg) + np.minimum(255, g * 2.2) * bg
    return np.clip(out + rng.normal(0, 4, f.shape), 0, 255).astype(np.uint8)


def jpeg(f, q=12):
    ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def motion_blur(f, k=9):
    kern = np.zeros((k, k), np.float32)
    kern[k // 2, :] = 1.0 / k
    return cv2.filter2D(f, -1, kern)


def occlude(f, eye_boxes, kind):
    if eye_boxes is None:
        return f
    f = f.copy()
    for j, e in enumerate(eye_boxes):
        c = e.mean(0)
        wd = float(np.ptp(e[:, 0]))
        if kind == "sunglasses":
            cv2.ellipse(f, (int(c[0]), int(c[1])), (int(wd * 0.85), int(wd * 0.53)), 0, 0, 360,
                        (25, 25, 28), -1)
        elif kind == "glare":
            ov = f.copy()
            cv2.ellipse(ov, (int(c[0]), int(c[1] - wd * 0.1)), (int(wd * 0.7), int(wd * 0.35)), -20, 0, 360,
                        (250, 250, 250), -1)
            f = cv2.addWeighted(ov, 0.75, f, 0.25, 0)
        elif kind == "one_eye" and j == 0:
            cv2.ellipse(f, (int(c[0]), int(c[1])), (int(wd * 1.3), int(wd * 1.0)), 0, 0, 360,
                        (90, 120, 170), -1)
    return f


def eye_boxes_from_clean(video, model):
    """Locate the eyes on the clean video so occluders sit where real ones would."""
    tr = FaceTracker(model)
    import mediapipe as mp
    cap = cv2.VideoCapture(video)
    out, i = [], 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        h, w = fr.shape[:2]
        res = tr._landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), i * 84 + 1)
        i += 1
        if res.face_landmarks:
            p = np.array([[q.x * w, q.y * h] for q in res.face_landmarks[0]])
            out.append((p[EYES[0]], p[EYES[1]]))
        else:
            out.append(out[-1] if out else None)
    tr.close()
    return out


def run(video, labels, model, transform, every=1):
    rng = np.random.default_rng(0)
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    tr = FaceTracker(model)
    det = BlinkDetector()
    found, px, lum, i, n, faces, hidden = [], [], [], 0, 0, 0, 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % every:
            i += 1
            continue
        f = tr.process(transform(fr, rng, i), i / fps)
        n += 1
        if f.face:
            faces += 1
            px.append(f.face_px)
            lum.append(f.luminance)
        b = det.update(f)
        hidden += det.eyes_hidden
        if b:
            found.append(round(b.t * fps))
        i += 1
    found += [round(b.t * fps) for b in det.flush()]
    tr.close()
    s = score(found, labels, tolerance=3 * every)
    q = assess(det.fps, statistics.median(px) if px else None,
               statistics.median(lum) if lum else None, det.noise, hidden / max(n, 1))
    return s, q, 100 * faces / max(n, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--labels", default=str(ROOT / "tests/data/intel_head_pose_male_labels.json"))
    args = ap.parse_args()
    labels = json.loads(Path(args.labels).read_text())
    model = str(ensure_model(data_dir()))
    boxes = eye_boxes_from_clean(args.video, model)
    conditions = [
        ("baseline (12 fps webcam)", lambda f, r, i: f, 1),
        ("blurry/low-res camera (40%)", lambda f, r, i: scale(f, 0.4), 1),
        ("far away (face 60% size)", lambda f, r, i: shrink(f, 0.6), 1),
        ("very far (face 40% size)", lambda f, r, i: shrink(f, 0.4), 1),
        ("6 fps camera", lambda f, r, i: f, 2),
        ("motion blur", lambda f, r, i: motion_blur(f), 1),
        ("heavy compression", lambda f, r, i: jpeg(f), 1),
        ("bright window behind", lambda f, r, i: backlit(f, r), 1),
        ("dim room + sensor noise", lambda f, r, i: dim(f, r), 1),
        ("hand over one eye", lambda f, r, i: occlude(f, boxes[i], "one_eye"), 1),
        ("glare on glasses", lambda f, r, i: occlude(f, boxes[i], "glare"), 1),
        ("sunglasses", lambda f, r, i: occlude(f, boxes[i], "sunglasses"), 1),
    ]
    print(f"{'condition':<28}{'precision':>10}{'recall':>8}{'face':>7}  quality -> what the app does")
    for name, fn, every in conditions:
        s, q, face = run(args.video, labels, model, fn, every)
        action = ("coaches normally" if q.level == "good" else
                  "coaches, notes reduced accuracy" if q.level == "fair" else
                  "pauses blink advice, asks user to fix" if q.level == "poor" else "unknown")
        prec = f"{s.precision:.2f}" if s.tp + s.fp else "  -- "
        print(f"{name:<28}{prec:>10}{s.recall:>8.2f}{face:>6.0f}%  {q.level:<5} -> {action}"
              + (f" ({q.reasons[0]})" if q.reasons and q.level != "good" else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

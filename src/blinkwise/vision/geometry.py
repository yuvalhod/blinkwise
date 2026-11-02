"""Pure geometry on MediaPipe face-mesh landmarks.

Everything here is a plain function over numpy arrays so it can be unit-tested
without a camera or a model.

Landmark indices refer to the 478-point MediaPipe Face Landmarker topology
(468 mesh points + 10 iris points).
"""

from __future__ import annotations

import math
from typing import Optional, Sequence, Tuple

import numpy as np

# Eye contours. Corners are (outer, inner); vertical pairs are (upper lid, lower lid)
# matched so each pair is roughly vertical in a frontal face.
# "Right"/"left" here are from the *subject's* point of view.
RIGHT_EYE_CORNERS = (33, 133)
RIGHT_EYE_PAIRS = ((160, 144), (159, 145), (158, 153))
LEFT_EYE_CORNERS = (263, 362)
LEFT_EYE_PAIRS = ((385, 380), (386, 374), (387, 373))

# Iris landmarks (only present in the 478-point refined model).
RIGHT_IRIS_CENTER, RIGHT_IRIS_H = 468, (469, 471)
LEFT_IRIS_CENTER, LEFT_IRIS_H = 473, (474, 476)

# Average human horizontal visible iris diameter is remarkably constant across
# adults (~11.7 mm +/- 0.5 mm), which lets a single webcam estimate distance.
IRIS_DIAMETER_MM = 11.7


def eye_aspect_ratio(pts: np.ndarray, corners: Tuple[int, int],
                     pairs: Sequence[Tuple[int, int]]) -> Tuple[float, float]:
    """Eye Aspect Ratio (Soukupova & Cech, 2016), generalised to N vertical pairs.

    Returns (ear, eye_width_px). EAR is ~0.25-0.4 for an open eye and drops
    toward 0 as the lids close; it is scale and in-plane-rotation invariant.
    """
    p_outer, p_inner = pts[corners[0], :2], pts[corners[1], :2]
    width = float(np.linalg.norm(p_outer - p_inner))
    if width < 1e-6:
        return 0.0, 0.0
    vertical = [np.linalg.norm(pts[a, :2] - pts[b, :2]) for a, b in pairs]
    return float(np.mean(vertical) / width), width


def both_eyes(pts: np.ndarray) -> Tuple[float, float, float, float]:
    """Return (ear_right, ear_left, width_right_px, width_left_px)."""
    er, wr = eye_aspect_ratio(pts, RIGHT_EYE_CORNERS, RIGHT_EYE_PAIRS)
    el, wl = eye_aspect_ratio(pts, LEFT_EYE_CORNERS, LEFT_EYE_PAIRS)
    return er, el, wr, wl


def iris_diameter_px(pts: np.ndarray) -> Optional[float]:
    """Mean horizontal iris diameter in pixels, or None without iris landmarks.

    Uses the larger of the two irises: a turned head foreshortens the far iris
    horizontally, while the near one stays closest to its true size.
    """
    if pts.shape[0] < 478:
        return None
    d_r = np.linalg.norm(pts[RIGHT_IRIS_H[0], :2] - pts[RIGHT_IRIS_H[1], :2])
    d_l = np.linalg.norm(pts[LEFT_IRIS_H[0], :2] - pts[LEFT_IRIS_H[1], :2])
    d = float(max(d_r, d_l))
    return d if d > 1e-3 else None


def focal_length_px(image_width: int, horizontal_fov_deg: float) -> float:
    """Pinhole focal length in pixels from the camera's horizontal field of view."""
    return (image_width / 2.0) / math.tan(math.radians(horizontal_fov_deg) / 2.0)


def distance_cm_from_iris(iris_px: Optional[float], focal_px: float) -> Optional[float]:
    """Similar triangles: distance = f * real_size / image_size."""
    if not iris_px:
        return None
    return focal_px * (IRIS_DIAMETER_MM / 10.0) / iris_px


def euler_from_matrix(m: np.ndarray) -> Tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees from MediaPipe's 4x4 facial transformation matrix.

    Conventions used throughout Blinkwise:
      yaw   > 0  -> face turned toward the image's right side
      pitch > 0  -> face tilted up (chin up)
      roll  > 0  -> head tilted clockwise in the image
    """
    r = np.asarray(m, dtype=float)[:3, :3]
    sy = math.hypot(r[0, 0], r[1, 0])
    if sy > 1e-6:
        pitch = math.atan2(r[2, 1], r[2, 2])
        yaw = math.atan2(-r[2, 0], sy)
        roll = math.atan2(r[1, 0], r[0, 0])
    else:  # gimbal lock; irrelevant for real faces but keep it total
        pitch = math.atan2(-r[1, 2], r[1, 1])
        yaw = math.atan2(-r[2, 0], sy)
        roll = 0.0
    # MediaPipe's canonical face model has +x rotation = chin down; flip so up is positive.
    # (Verified on real video: looking at a keyboard reads about -28 deg.)
    return math.degrees(yaw), -math.degrees(pitch), math.degrees(roll)


def face_luminance(gray: np.ndarray, pts: np.ndarray) -> Optional[float]:
    """Mean 0-255 luminance in the face bounding box (lighting heuristic)."""
    h, w = gray.shape[:2]
    x0, y0 = np.clip(pts[:, :2].min(0), 0, [w - 1, h - 1]).astype(int)
    x1, y1 = np.clip(pts[:, :2].max(0), 0, [w - 1, h - 1]).astype(int)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return float(gray[y0:y1, x0:x1].mean())


# Iris landmarks centre within the eye, mapped to an approximate rotation angle.
# The visible eye opening is ~30 mm wide and the eyeball radius ~12 mm, so an
# iris offset of r (as a fraction of the half-width, 15 mm) is ~asin(1.25 r).
EYE_HALF_WIDTH_MM, EYEBALL_RADIUS_MM = 15.0, 12.0


def eye_in_head_yaw(pts: np.ndarray) -> Optional[float]:
    """Horizontal eye rotation relative to the head, degrees (+ = toward image right).

    Diagnostic only. At typical webcam resolution the iris is ~10 px wide, so one
    pixel of landmark error is ~6 degrees, and the estimate degrades past ~30 degrees
    of head yaw. Too coarse to split screens by (reading across one wide monitor
    sweeps the eyes +/-20 degrees), so screen zones use head yaw instead.
    """
    if pts.shape[0] < 478:
        return None
    vals = []
    for (a, b), c in ((RIGHT_EYE_CORNERS, RIGHT_IRIS_CENTER), (LEFT_EYE_CORNERS, LEFT_IRIS_CENTER)):
        p1, p2, ic = pts[a, :2], pts[b, :2], pts[c, :2]
        if p1[0] > p2[0]:
            p1, p2 = p2, p1                    # orient the axis toward image +x
        axis = p2 - p1
        half = np.linalg.norm(axis) / 2
        if half < 1e-3:
            continue
        r = float(np.dot(ic - (p1 + p2) / 2, axis / (2 * half)) / half)
        vals.append(math.degrees(math.asin(float(np.clip(r * EYE_HALF_WIDTH_MM / EYEBALL_RADIUS_MM, -1, 1)))))
    return float(np.mean(vals)) if vals else None


_RIGHT_EYE_ALL = (33, 133, 159, 145, 160, 144, 158, 153)
_LEFT_EYE_ALL = (263, 362, 386, 374, 385, 380, 387, 373)
_RIGHT_IRIS_RING = (469, 470, 471, 472)
_LEFT_IRIS_RING = (474, 475, 476, 477)


def eye_visibility(gray: np.ndarray, pts: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
    """Per-eye (right, left) iris contrast: how much darker the iris is than the rest
    of the eye opening, relative to face brightness.

    MediaPipe *guesses* eyelid landmarks even when the eyes are hidden, so we check
    the pixels. Measured on real video: visible eyes ~0.07 (10th pct 0.05),
    sunglasses ~0.00, glare on glasses negative. A blink also hides the iris
    briefly, so callers smooth this over ~1.5 s before using it.
    """
    if pts.shape[0] < 478:
        return None, None
    h, w = gray.shape[:2]
    fx0, fy0 = np.clip(pts[:, :2].min(0), 0, [w - 1, h - 1]).astype(int)
    fx1, fy1 = np.clip(pts[:, :2].max(0), 0, [w - 1, h - 1]).astype(int)
    if fx1 - fx0 < 8 or fy1 - fy0 < 8:
        return None, None
    ref = float(np.median(gray[fy0:fy1, fx0:fx1])) + 1.0
    out = []
    for eye, center, ring in ((_RIGHT_EYE_ALL, RIGHT_IRIS_CENTER, _RIGHT_IRIS_RING),
                              (_LEFT_EYE_ALL, LEFT_IRIS_CENTER, _LEFT_IRIS_RING)):
        e = pts[list(eye), :2]
        x0, y0 = np.clip(e.min(0), 0, [w - 1, h - 1]).astype(int)
        x1, y1 = np.clip(e.max(0), 0, [w - 1, h - 1]).astype(int)
        if x1 - x0 < 4 or y1 - y0 < 2:
            out.append(None)
            continue
        roi = gray[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
        c = pts[center, :2]
        r = max(1.5, float(np.ptp(pts[list(ring), 0])) / 2)
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        inside = (xx - c[0]) ** 2 + (yy - c[1]) ** 2 <= r * r
        if inside.sum() < 2 or (~inside).sum() < 2:
            out.append(0.0)
            continue
        out.append(float((roi[~inside].mean() - roi[inside].mean()) / ref))
    return out[0], out[1]

"""Low-light pre-processing before face landmarking.

Measured on a held-out real video darkened to a dim-room level with sensor
noise (scripts in docs/ARCHITECTURE.md, "Low light"):

    pipeline              recall   precision   cost
    none                  0.37     1.00        -
    gamma                 0.19     0.56        1.2 ms   (amplifies noise -> jitter)
    gamma -> blur 5x5     0.59     1.00        1.5 ms   <- used
    bilateral -> gamma    0.67     0.95        25 ms    (too slow, adds false blinks)
    CLAHE                 0.19     1.00        3.0 ms

So we brighten with a gamma curve (mapping the frame mean to ~45% grey), then
apply a small Gaussian blur to suppress the amplified sensor noise. It runs
only on dark frames, so normal lighting is untouched.
"""

from __future__ import annotations

import numpy as np

DARK_MEAN = 70.0     # mean grey level (0-255) below which a frame counts as dark
TARGET = 0.45


def is_dark(frame_bgr: np.ndarray) -> bool:
    return float(frame_bgr[::8, ::8].mean()) < DARK_MEAN


def enhance_low_light(frame_bgr: np.ndarray) -> np.ndarray:
    import cv2

    mean = max(float(frame_bgr[::4, ::4].mean()), 1.0)
    g = np.log(TARGET) / np.log(mean / 255.0)
    lut = np.clip(((np.arange(256) / 255.0) ** g) * 255.0, 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(cv2.LUT(frame_bgr, lut), (5, 5), 0)

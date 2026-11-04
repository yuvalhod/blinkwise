"""The per-frame feature record that flows from vision -> engine.

This is the *only* thing that leaves the vision layer. It contains a handful
of numbers, never pixels, which is what makes Blinkwise private by design and
lets the whole engine be tested with synthetic data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class FrameFeatures:
    t: float                              # seconds (monotonic clock or video time)
    face: bool                            # was a face found?
    ear_right: float = 0.0                # eye aspect ratios (subject's right/left)
    ear_left: float = 0.0
    width_right: float = 0.0              # eye widths in px (proxy for which eye faces the camera)
    width_left: float = 0.0
    yaw: float = 0.0                      # head pose, degrees (see geometry.euler_from_matrix)
    pitch: float = 0.0
    roll: float = 0.0
    distance_cm: Optional[float] = None   # iris-based viewing distance estimate
    luminance: Optional[float] = None     # mean face brightness 0-255
    blink_score: Optional[float] = None   # MediaPipe eyeBlink blendshape mean (diagnostic only)
    faces: int = 0                        # faces in view (the user is chosen among them)
    face_px: Optional[float] = None       # face width in pixels (tracking-quality signal)
    vis_right: Optional[float] = None     # per-eye iris contrast (eye visibility), see geometry
    vis_left: Optional[float] = None
    eye_yaw: Optional[float] = None       # eye-in-head horizontal gaze, degrees (diagnostic, coarse)
    extrapolated: bool = False            # burst mode: camera resting, last pose carried forward
                                          # (no eye data, so no blink statistics accrue)

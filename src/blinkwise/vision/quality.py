"""How much should we trust what the camera is telling us right now?

Wrong advice is worse than no advice: telling someone they blink 4 times a
minute because a dim, low-resolution image hides half their blinks erodes
trust in everything else. So we continuously grade tracking quality, show it,
and suppress blink-based coaching when it's poor.

Signals (all cheap, all already computed):
  * frame rate        - below ~10 fps short blinks fall between frames
  * face size (px)    - the eye opening spans only a few pixels on small faces
  * face brightness   - dim faces give noisy landmarks; blown-out ones lose lid edges
  * signal noise      - the blink detector's own robust noise estimate, the most
                        direct measure of whether a dip can be told from jitter
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

GOOD, FAIR, POOR = "good", "fair", "poor"
_RANK = {GOOD: 0, FAIR: 1, POOR: 2}


@dataclass
class Quality:
    level: str                         # good | fair | poor | unknown
    reasons: List[str] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)

    @property
    def trustworthy(self) -> bool:
        return self.level in (GOOD, FAIR)


def assess(fps: float, face_px: Optional[float], luminance: Optional[float],
           noise: Optional[float]) -> Quality:
    if face_px is None or fps <= 0:
        return Quality("unknown")
    level, reasons, tips = GOOD, [], []

    def worse(new: str, reason: str, tip: str) -> None:
        nonlocal level
        if _RANK[new] > _RANK[level]:
            level = new
        reasons.append(reason)
        if tip not in tips:
            tips.append(tip)

    if fps < 10:
        worse(POOR, f"low frame rate ({fps:.0f} fps)", "Close other apps using the camera, or add light "
              "(many webcams lower their frame rate in dim rooms).")
    elif fps < 18:
        worse(FAIR, f"frame rate {fps:.0f} fps (blink completeness needs 20+)", "Add light: webcams "
              "often drop to 15 fps in dim rooms.")
    if face_px < 70:
        worse(POOR, f"face is small in the image ({face_px:.0f} px wide)", "Sit closer to the camera "
              "or use a higher camera resolution.")
    elif face_px < 110:
        worse(FAIR, f"face is fairly small ({face_px:.0f} px wide)", "Sitting a little closer to the "
              "camera improves accuracy.")
    if luminance is not None:
        if luminance < 35:
            worse(POOR, "face is very dark", "Turn on a light in front of you (not behind you).")
        elif luminance < 55:
            worse(FAIR, "face is dimly lit", "More light on your face improves accuracy.")
        elif luminance > 225:
            worse(FAIR, "face is over-exposed", "Reduce direct light on your face or move away from "
                  "a bright window.")
    if noise is not None:
        if noise > 0.06:
            worse(POOR, "eye tracking is very jittery", "Add light and keep the camera steady.")
        elif noise > 0.035:
            worse(FAIR, "eye tracking is somewhat jittery", "More light usually reduces jitter.")
    return Quality(level, reasons, tips)

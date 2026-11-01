"""Events the engine emits. UIs, storage and tests subscribe to these."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..vision.blink import Blink


@dataclass
class BlinkEvent:
    blink: Blink
    zone: Optional[int] = None


@dataclass
class StareCue:
    """No blink for a while: show a gentle blink prompt (Nosch et al. 2015)."""
    seconds_since_blink: float


@dataclass
class Suggestion:
    rule: str
    severity: str                 # "info" | "warn" | "high"
    title: str
    message: str
    refs: List[str] = field(default_factory=list)
    notify: bool = False          # should the UI surface this as a notification now?
    data: Dict[str, Any] = field(default_factory=dict)
    t: float = 0.0


@dataclass
class BreakDue:
    kind: str                     # "micro" (20-20-20) | "long"
    seconds: float
    reason: str
    exercise: Optional[str] = None


@dataclass
class BreakEnded:
    kind: str
    outcome: str                  # "rested" | "timer" | "skipped" | "missed"


@dataclass
class MinuteSummary:
    """One row of history (aggregated numbers only, never images)."""
    t: float
    observed_s: float
    blinks: int
    judged: int
    incomplete: int
    long: int
    max_stare_s: float
    distance_cm: Optional[float]
    pitch: Optional[float]
    yaw: Optional[float]
    luminance: Optional[float]
    zones: int
    switches_per_min: float

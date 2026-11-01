"""User settings and on-disk locations."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

log = logging.getLogger(__name__)


def data_dir() -> Path:
    """Per-user directory for the model, settings and the local history database."""
    override = os.environ.get("BLINKWISE_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Blinkwise"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Blinkwise"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "blinkwise"


@dataclass
class Settings:
    # --- capture -------------------------------------------------------------
    camera: Union[int, str] = 0
    max_fps: float = 24.0                 # cap processing rate; 20+ fps enables blink-completeness analysis
    camera_hfov_deg: float = 60.0         # typical laptop webcam; refine with `blinkwise calibrate`
    focal_px: Optional[float] = None      # set by calibration, overrides camera_hfov_deg
    camera_position: str = "top"          # "top" (above the main screen, the common case) or "bottom"

    # --- blink coaching ------------------------------------------------------
    stare_seconds: float = 10.0           # show a blink cue after this long without blinking
    blink_cue: str = "subtle"             # "subtle" on-screen cue, "notify", or "off"
    low_blink_rate: float = 10.0          # blinks/min (5-min window) considered low
    very_low_blink_rate: float = 6.0

    # --- breaks --------------------------------------------------------------
    micro_break_minutes: float = 20.0     # 20-20-20 rule
    micro_break_seconds: float = 20.0
    long_break_minutes: float = 60.0      # NIOSH-style hourly supplementary break
    long_break_seconds: float = 300.0
    adaptive_breaks: bool = True          # bring breaks forward when blink rate is low
    break_style: str = "gentle"           # "gentle" (dismissable overlay) or "notify"

    # --- environment ---------------------------------------------------------
    min_distance_cm: float = 50.0         # AOA: 20-28 in (~50-70 cm)

    # --- general -------------------------------------------------------------
    profile: str = "adult"                # "adult" or "young" (adds myopia-prevention guidance)
    min_notification_gap_s: float = 180.0 # never nag more often than this
    dashboard_port: int = 8765
    store_history: bool = True

    @classmethod
    def path(cls) -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        if not p.exists():
            return cls()
        try:
            raw = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            log.warning("Ignoring unreadable settings file %s: %s", p, e)
            return cls()
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self) -> Path:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dataclasses.asdict(self), indent=2))
        return p

    def update(self, **kwargs) -> "Settings":
        known = {f.name: f for f in dataclasses.fields(self)}
        for k, v in kwargs.items():
            if k not in known:
                raise KeyError(f"Unknown setting {k!r}. Known: {', '.join(sorted(known))}")
            setattr(self, k, _coerce(v, getattr(self, k)))
        return self


def _coerce(value, current):
    """Coerce CLI strings to the type of the current value."""
    if not isinstance(value, str):
        return value
    if isinstance(current, bool):
        return value.lower() in ("1", "true", "yes", "on")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(value) if value.lstrip("-").isdigit() else value
    if isinstance(current, float):
        return float(value)
    if current is None:
        try:
            return float(value)
        except ValueError:
            return value
    return value

"""User settings and on-disk locations."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
from dataclasses import dataclass, field
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


# Coaching styles: how present Blinkwise is in your day. Each sets several fields at once;
# changing any of these fields afterwards makes the preset "custom".
PRESETS = {
    "gentle": dict(blink_cue="menubar", adaptive_cues=False, stare_seconds=15.0,
                   break_style="notify", skip_delay_s=0.0, micro_break_minutes=30.0,
                   long_break_minutes=90.0, notify_suggestions="none",
                   min_notification_gap_s=1800.0),
    "balanced": dict(blink_cue="subtle", adaptive_cues=True, stare_seconds=10.0,
                     break_style="gentle", skip_delay_s=0.0, micro_break_minutes=20.0,
                     long_break_minutes=60.0, notify_suggestions="important",
                     min_notification_gap_s=180.0),
    "coach": dict(blink_cue="big", adaptive_cues=True, stare_seconds=8.0,
                  break_style="immersive", skip_delay_s=5.0, micro_break_minutes=20.0,
                  long_break_minutes=60.0, notify_suggestions="all",
                  min_notification_gap_s=120.0),
}
PRESET_FIELDS = sorted({k for p in PRESETS.values() for k in p})

# Settings a UI may change, with allowed values (lists) or (min, max) ranges.
EDITABLE = {
    "preset": list(PRESETS) + ["custom"],
    "blink_cue": ["menubar", "subtle", "big", "notify", "off"],
    "adaptive_cues": [True, False],
    "stare_seconds": (4.0, 60.0),
    "break_style": ["notify", "gentle", "immersive"],
    "skip_delay_s": (0.0, 20.0),
    "micro_break_minutes": (5.0, 120.0),
    "long_break_minutes": (20.0, 240.0),
    "notify_suggestions": ["none", "important", "all"],
    "daily_summary": None,      # "HH:MM" or ""
    "profile": ["adult", "young"],
    "store_history": [True, False],
    "history_days": [7, 30, 90, 365],
    "setup_done": [True, False],
    "battery_saver": ["auto", "always", "off"],
    "during_calls": ["quiet", "pause", "off"],
    "check_updates": [True, False],
    "sampling": ["continuous", "burst"],
    "performance": ["efficient", "max"],
}


@dataclass
class Settings:
    # --- capture -------------------------------------------------------------
    camera: Union[int, str] = 0
    max_fps: float = 24.0                 # cap processing rate; 20+ fps enables blink-completeness analysis
    camera_hfov_deg: float = 60.0         # typical laptop webcam; refine with `blinkwise calibrate`
    focal_px: Optional[float] = None      # set by calibration, overrides camera_hfov_deg
    focal_px_width: int = 1280            # ...measured at this image width
    camera_position: str = "top"          # "top" (above the main screen, the common case) or "bottom"
    battery_saver: str = "auto"           # "auto": 12 fps on battery | "always" | "off"
    sampling: str = "continuous"          # "burst": camera on 1 minute in every 5 (light mostly off)
    performance: str = "efficient"        # "efficient": 15 fps + 1 min in 5 at full rate | "max"
    # In a video call: "quiet" (no pop-ups, keep measuring), "pause" (release the camera), "off".
    # Windows/Linux webcams are usually single-user, so there we hand the camera over.
    during_calls: str = field(default_factory=lambda: "quiet" if sys.platform == "darwin" else "pause")

    # --- blink coaching ------------------------------------------------------
    stare_seconds: float = 10.0           # show a blink cue after this long without blinking
    preset: str = "balanced"              # "gentle" | "balanced" | "coach" | "custom" (see PRESETS)
    blink_cue: str = "subtle"             # "menubar" icon blink, "subtle" small eye, "big" centred prompt,
                                          # "notify", "off"
    adaptive_cues: bool = True            # step the cue up/down based on whether you respond to it
    low_blink_rate: float = 10.0          # blinks/min (5-min window) considered low
    very_low_blink_rate: float = 6.0

    # --- breaks --------------------------------------------------------------
    micro_break_minutes: float = 20.0     # 20-20-20 rule
    micro_break_seconds: float = 20.0
    long_break_minutes: float = 60.0      # NIOSH-style hourly supplementary break
    long_break_seconds: float = 300.0
    adaptive_breaks: bool = True          # bring breaks forward when blink rate is low
    break_style: str = "gentle"           # "notify" | "gentle" (small card) | "immersive" (full screen)
    skip_delay_s: float = 0.0             # immersive breaks: Skip appears after this many seconds

    # --- environment ---------------------------------------------------------
    min_distance_cm: float = 50.0         # AOA: 20-28 in (~50-70 cm)

    # --- general -------------------------------------------------------------
    profile: str = "adult"                # "adult" or "young" (adds myopia-prevention guidance)
    min_notification_gap_s: float = 180.0 # never nag more often than this
    notify_suggestions: str = "important" # "none" | "important" | "all"
    daily_summary: str = "18:00"          # local time for the end-of-day summary, "" = off
    setup_done: bool = False              # first-run setup guide completed
    dashboard_port: int = 8765
    tray: bool = True                     # menu-bar / system-tray icon
    store_history: bool = True
    history_days: int = 90                # history older than this is deleted automatically
    check_updates: bool = True            # once a day, anonymous; never downloads anything
    blink_overrides: dict = field(default_factory=dict)  # personal detector settings (calibration)
    # --- family sharing (off until a parent's pairing code is entered) -------
    family_url: str = ""                  # the parent's family server
    family_token: str = ""                # this computer's device token (secret)
    family_name: str = ""                 # the name the parent gave this child
    family_share_checkin: bool = False    # also share the weekly eye check-in score
    family_removed: bool = False          # the parent removed this computer
    parent_pin: str = ""                  # salted PBKDF2 hash; locks settings in kids mode

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

    SECRET_FIELDS = ("family_token", "parent_pin")

    def public_dict(self) -> dict:
        """For UIs: secrets replaced by whether they're set."""
        d = dataclasses.asdict(self)
        for k in self.SECRET_FIELDS:
            d[k] = bool(d[k])
        return d

    def apply_preset(self, name: str) -> "Settings":
        if name not in PRESETS:
            raise KeyError(f"Unknown preset {name!r}. Choose from {', '.join(PRESETS)}")
        for k, v in PRESETS[name].items():
            setattr(self, k, v)
        self.preset = name
        return self

    def apply_ui_changes(self, changes: dict) -> "Settings":
        """Validate and apply changes coming from the dashboard or menu (untrusted input)."""
        if "preset" in changes and changes["preset"] in PRESETS:
            self.apply_preset(changes["preset"])
        touched_preset_field = False
        for k, v in changes.items():
            if k == "preset" or k not in EDITABLE:
                continue
            rule = EDITABLE[k]
            cur = getattr(self, k)
            if isinstance(cur, bool):
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif isinstance(cur, float):
                v = float(v)
            elif isinstance(cur, int):
                v = int(v)
            if rule is None:                      # daily_summary
                v = str(v).strip()
                if v and not _valid_hhmm(v):
                    raise ValueError(f"{k} must be HH:MM or empty")
            elif isinstance(rule, tuple):
                if not rule[0] <= v <= rule[1]:
                    raise ValueError(f"{k} must be between {rule[0]:g} and {rule[1]:g}")
            elif v not in rule:
                raise ValueError(f"{k} must be one of {rule}")
            if getattr(self, k) != v and k in PRESET_FIELDS:
                touched_preset_field = True
            setattr(self, k, v)
        if touched_preset_field:
            self.preset = "custom"
        return self

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


def _valid_hhmm(v: str) -> bool:
    try:
        h, m = v.split(":")
        return 0 <= int(h) < 24 and 0 <= int(m) < 60 and len(m) == 2
    except ValueError:
        return False

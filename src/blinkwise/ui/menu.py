"""What you see when you click the eye in the menu bar.

Design rules
  * Glanceable: the top four lines answer "how am I doing right now?" in plain
    words, with no jargon or decimals.
  * Few actions, most common first: take a break, pause, open the dashboard.
  * Everything else (settings, history, science) lives in the dashboard.

The model is plain data so it's unit-tested and rendered identically by the
real tray backend (pystray) and by the design mock-up script.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Item:
    text: str = ""
    action: Optional[str] = None        # e.g. "break_now", "pause:30", "cue:menubar"
    enabled: bool = True
    checked: Optional[bool] = None      # radio/check state, None = not checkable
    submenu: List["Item"] = field(default_factory=list)
    separator: bool = False
    info: bool = False                  # a status line (shown greyed, not clickable)

    @staticmethod
    def sep() -> "Item":
        return Item(separator=True)

    @staticmethod
    def line(text: str) -> "Item":
        return Item(text=text, enabled=False, info=True)


STYLE_CHOICES = (("gentle", "Gentle"), ("balanced", "Balanced"), ("coach", "Coach"))

CUE_CHOICES = (("menubar", "Blink the menu bar icon"),
               ("subtle", "Small eye on screen"),
               ("notify", "Notification"),
               ("off", "Off"))


def rate_word(rate: Optional[float]) -> str:
    if rate is None:
        return "measuring..."
    if rate < 6:
        return f"{rate:.0f} a minute, very low"
    if rate < 10:
        return f"{rate:.0f} a minute, low"
    if rate < 15:
        return f"{rate:.0f} a minute, OK"
    return f"{rate:.0f} a minute, healthy"


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    m = seconds // 60
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


def status_title(snap: Dict[str, Any]) -> str:
    if snap.get("consent_needed"):
        return "Camera off until you review and start"
    call, mode = snap.get("in_call"), snap.get("call_mode", "quiet")
    if call and mode != "off" and not snap.get("paused"):
        return "In a call - camera off" if mode == "pause" else "In a call - quiet"
    if snap.get("quiet_for_s") and not snap.get("paused"):
        return f"Quiet ({duration(snap['quiet_for_s'])} left)"
    if snap.get("paused"):
        until = snap.get("paused_for_s")
        return "Paused - camera off" + (f" ({duration(until)} left)" if until else "")
    if snap.get("camera_resting") and not snap.get("paused"):
        return f"Camera resting (back in {duration(snap.get('camera_back_in_s') or 0)})"
    if snap.get("camera_error"):
        return "Camera unavailable - retrying"
    if not snap.get("running", True):
        return "Starting..."
    if (snap.get("quality") or {}).get("level") == "poor":
        return "Can't see your eyes clearly"
    if not snap.get("face"):
        return "Watching - no one in view"
    return "Watching your blinks"


def build_menu(snap: Dict[str, Any], *, blink_cue: str, autostart: Optional[bool],
               cue_choices=CUE_CHOICES) -> List[Item]:
    items: List[Item] = [Item(text=f"Blinkwise: {status_title(snap)}", enabled=False)]
    if not snap.get("paused"):
        rate = snap.get("blink_rate_5m")
        if rate is None:
            rate = snap.get("blink_rate_1m")
        items.append(Item.line(f"Blinking: {rate_word(rate)}"))
        since = snap.get("seconds_since_blink")
        if since is not None and snap.get("face"):
            items.append(Item.line(f"Last blink: {duration(since)} ago"))
        if snap.get("break_active"):
            items.append(Item.line("Eye break: now - look at something far away"))
        elif snap.get("next_break_s") is not None:
            items.append(Item.line(f"Next eye break: in {duration(snap['next_break_s'])}"))
    today = snap.get("today") or {}
    if today.get("screen_minutes"):
        items.append(Item.line(f"Screen time today: {duration(today['screen_minutes'] * 60)}"))
        if today.get("device_minutes", 0) >= 1:
            items.append(Item.line(f"Phone time today: {duration(today['device_minutes'] * 60)}"))
        if today.get("multitask_minutes"):
            items.append(Item.line(f"Switching laptop and phone: {today['multitask_minutes']} min"))
    if snap.get("family_sharing"):
        items.append(Item.line("Sharing weekly totals with a parent"))
    items.append(Item.sep())

    if snap.get("consent_needed"):
        items.append(Item(text="Review and start...", action="setup"))
    elif snap.get("break_active"):
        items.append(Item(text="Skip this break", action="skip_break"))
    else:
        items.append(Item(text="Take a 20-second eye break", action="break_now",
                          enabled=not snap.get("paused")))
    if snap.get("quiet_for_s"):
        items.append(Item(text=f"End quiet time ({duration(snap['quiet_for_s'])} left)",
                          action="quiet:0"))
    elif not snap.get("paused"):
        items.append(Item(text="Quiet for 1 hour", action="quiet:60"))
    if snap.get("paused"):
        items.append(Item(text="Resume", action="resume"))
    else:
        items.append(Item(text="Pause camera", submenu=[
            Item(text="For 30 minutes", action="pause:30"),
            Item(text="For 1 hour", action="pause:60"),
            Item(text="Until I resume", action="pause:0"),
        ]))
    items.append(Item.sep())
    preset = snap.get("preset", "balanced")
    items.append(Item(text="Coaching style", submenu=[
        Item(text=label, action=f"preset:{key}", checked=(preset == key))
        for key, label in STYLE_CHOICES] + ([Item.line("Custom")]
                                            if preset == "custom" else [])))
    items.append(Item(text="Open dashboard...", action="dashboard"))
    if snap.get("checkin_due"):
        items.append(Item(text="Weekly eye check-in...", action="checkin"))
    poor = (snap.get("quality") or {}).get("level") == "poor"
    items.append(Item(text="Fix camera setup..." if poor else "Check camera setup...", action="setup"))
    if autostart is not None:
        items.append(Item(text="Start at login", action="autostart", checked=autostart))
    if snap.get("update"):
        items.append(Item(text=f"Update available: {snap['update']['version']}...", action="update"))
    items.append(Item.sep())
    items.append(Item(text="Quit Blinkwise", action="quit"))
    return items


def icon_state(snap: Dict[str, Any]) -> tuple:
    """(state, badge) for ui.icon.render."""
    if snap.get("paused"):
        return "closed", False                 # camera off: eye closed
    if not snap.get("face"):
        return "away", bool(snap.get("break_active"))
    return "open", bool(snap.get("break_active"))   # watching: eye open

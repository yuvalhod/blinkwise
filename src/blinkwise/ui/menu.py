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
    if snap.get("paused"):
        until = snap.get("paused_for_s")
        return "Paused - camera off" + (f" ({duration(until)} left)" if until else "")
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
        brk = today.get("breaks_taken", 0)
        items.append(Item.line(f"Today: {duration(today['screen_minutes'] * 60)} on screen, "
                               f"{brk} break{'s' if brk != 1 else ''}"))
    items.append(Item.sep())

    if snap.get("break_active"):
        items.append(Item(text="Skip this break", action="skip_break"))
    else:
        items.append(Item(text="Take a 20-second eye break", action="break_now",
                          enabled=not snap.get("paused")))
    if snap.get("paused"):
        items.append(Item(text="Resume", action="resume"))
    else:
        items.append(Item(text="Pause", submenu=[
            Item(text="For 30 minutes", action="pause:30"),
            Item(text="For 1 hour", action="pause:60"),
            Item(text="Until I resume", action="pause:0"),
        ]))
    items.append(Item.sep())
    items.append(Item(text="Open dashboard...", action="dashboard"))
    poor = (snap.get("quality") or {}).get("level") == "poor"
    items.append(Item(text="Fix camera setup..." if poor else "Check camera setup...", action="setup"))
    items.append(Item(text="Blink reminder", submenu=[
        Item(text=label, action=f"cue:{key}", checked=(blink_cue == key))
        for key, label in cue_choices]))
    if autostart is not None:
        items.append(Item(text="Start at login", action="autostart", checked=autostart))
    items.append(Item.sep())
    items.append(Item(text="Quit Blinkwise", action="quit"))
    return items


def icon_state(snap: Dict[str, Any]) -> tuple:
    """(state, badge) for ui.icon.render."""
    if snap.get("paused"):
        return "paused", False
    if not snap.get("face"):
        return "away", bool(snap.get("break_active"))
    return "watching", bool(snap.get("break_active"))

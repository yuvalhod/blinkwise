"""The menu-bar / system-tray icon: a closed eye with eyelashes.

Drawn procedurally (no image assets) so it's crisp at every size and can be
re-coloured. On macOS it's used as a *template* image: pure black + alpha, and
the system tints it for light/dark menu bars and the highlighted state.

States
  watching  closed eye with lashes (the brand mark: "rest your eyes")
  open      open eye (used as frames of the blink animation)
  half      half-closed eye (blink animation)
  paused    closed eye with a slash (camera is off)
  away      closed eye, faded (nobody in front of the camera)
Badge
  a small dot at the top-right when a break is due
"""

from __future__ import annotations

import math
from typing import List, Tuple

STATES = ("watching", "open", "half", "paused", "away")
BLINK_FRAMES = ("half", "open", "open", "half", "watching")   # played as the stare cue

Color = Tuple[int, int, int, int]


def render(state: str = "watching", size: int = 44, color: Color = (0, 0, 0, 255),
           badge: bool = False):
    """Return a PIL RGBA image of the icon. `size` is the square pixel size
    (44 = macOS menu bar @2x; 22 @1x; 16/32 for Windows/Linux trays)."""
    from PIL import Image, ImageDraw

    if state not in STATES:
        raise ValueError(f"unknown icon state {state!r}")
    ss = 4                                  # supersample for smooth curves
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = color if state != "away" else (color[0], color[1], color[2], int(color[3] * 0.45))
    small = size < 32
    # Thicker strokes and fewer lashes when small, so it stays legible at 16-22 px.
    lw = max(2, round(S * (0.10 if small else 0.075)))
    n_lashes = 3 if small else 5
    rx = S * 0.44                           # half width of the eye
    cx = S / 2

    if state in ("watching", "paused", "away"):
        sag, lash = S * 0.18, S * 0.17
        cy = S / 2 - (sag + lash) / 2       # centre lid + lashes vertically
        _poly(d, _arc_points(cx, cy, rx, sag), c, lw)
        _lashes(d, cx, cy, rx, lash, lw, c, up=False, curve=sag, n=n_lashes)
    elif state == "half":
        h, lash = S * 0.09, S * 0.15
        cy = S / 2 - lash / 2
        _open_eye(d, cx, cy, rx, h, lw, c, pupil=False)
        _lashes(d, cx, cy + h, rx, lash, lw, c, up=False, curve=h, n=n_lashes)
    else:  # open
        h, lash = S * 0.20, S * 0.14
        cy = S / 2 + lash / 2
        _open_eye(d, cx, cy, rx, h, lw, c, pupil=True)
        _lashes(d, cx, cy - h, rx, lash, lw, c, up=True, curve=h, n=n_lashes)

    if state == "paused":
        # Slash with a transparent "cut" alongside it so it separates from the lid.
        a, b = (S * 0.16, S * 0.86), (S * 0.86, S * 0.16)
        nx, ny = lw * 0.9, lw * 0.9            # offset toward the upper-left
        d.line([(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny)], fill=(0, 0, 0, 0), width=lw * 2)
        d.line([a, b], fill=c, width=lw)
    if badge:
        r = S * (0.15 if small else 0.13)
        bx, by = S - r - S * 0.01, r + S * 0.01
        d.ellipse([bx - r - lw, by - r - lw, bx + r + lw, by + r + lw], fill=(0, 0, 0, 0))
        d.ellipse([bx - r, by - r, bx + r, by + r], fill=c)
    return img.resize((size, size), Image.LANCZOS)


def _arc_points(cx: float, cy: float, rx: float, sag: float, n: int = 40) -> List[Tuple[float, float]]:
    """A smooth lid curve from (cx-rx, cy) to (cx+rx, cy), sagging by `sag` in the middle."""
    return [(cx - rx + 2 * rx * i / n, cy + sag * math.sin(math.pi * i / n)) for i in range(n + 1)]


def _poly(d, pts, c, lw) -> None:
    d.line(pts, fill=c, width=lw, joint="curve")
    r = lw / 2
    for x, y in (pts[0], pts[-1]):          # round caps
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)


def _open_eye(d, cx, cy, rx, h, lw, c, pupil: bool) -> None:
    _poly(d, _arc_points(cx, cy, rx, -h), c, lw)      # upper lid
    _poly(d, _arc_points(cx, cy, rx, h), c, lw)       # lower lid
    if pupil:
        r = h * 0.72
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)


def _lashes(d, cx, cy, rx, length, lw, c, up: bool, curve: float, n: int = 5) -> None:
    """Lashes along the lid, fanning outward like real lashes."""
    sign = -1 if up else 1
    for i in range(n):
        f = (i + 1) / (n + 1)                # positions along the lid (avoid the corners)
        x = cx - rx + 2 * rx * f
        y = cy + sign * abs(curve) * math.sin(math.pi * f)
        spread = (f - 0.5) * 1.2             # tilt outward toward the nearer corner (radians)
        _poly(d, [(x, y), (x + math.sin(spread) * length, y + sign * math.cos(spread) * length)],
              c, max(2, int(lw * 0.8)))


def blink_animation(size: int = 44, color: Color = (0, 0, 0, 255)):
    """Frames for the menu-bar stare cue: the eye opens and closes ("blink with me")."""
    return [render(s, size, color) for s in BLINK_FRAMES]

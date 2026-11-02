"""The menu-bar / system-tray icon: an eye with eyelashes.

Drawn procedurally (no image assets) so it's crisp at every size and can be
re-coloured. On macOS it's used as a *template* image: pure black + alpha, and
the system tints it for light/dark menu bars and the highlighted state.

States
  open      open eye: Blinkwise is on and watching
  closed    closed eye with lashes: camera off (paused)
  away      open eye, faded: on, but nobody is in front of the camera
  half      half-closed eye: only used mid-blink in the stare-cue animation
Badge
  a small dot at the bottom-right when a break is due
"""

from __future__ import annotations

import math
from typing import List, Tuple

STATES = ("open", "closed", "away", "half")
BLINK_FRAMES = ("half", "closed", "closed", "half", "open")   # the stare cue: the eye blinks

Color = Tuple[int, int, int, int]


def render(state: str = "open", size: int = 44, color: Color = (0, 0, 0, 255),
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

    if state == "closed":
        sag, lash = S * 0.18, S * 0.17
        cy = S / 2 - (sag + lash) / 2       # centre lid + lashes vertically
        _poly(d, _arc_points(cx, cy, rx, sag), c, lw)
        _lashes(d, cx, cy, rx, lash, lw, c, up=False, curve=sag, n=n_lashes)
    elif state == "half":
        h, lash = S * 0.09, S * 0.15
        cy = S / 2 - lash / 2
        _open_eye(d, cx, cy, rx, h, lw, c, pupil=False)
        _lashes(d, cx, cy + h, rx, lash, lw, c, up=False, curve=h, n=n_lashes)
    else:  # open / away
        h, lash = S * 0.20, S * 0.14
        cy = S / 2 + lash / 2
        _open_eye(d, cx, cy, rx, h, lw, c, pupil=True)
        _lashes(d, cx, cy - h, rx, lash, lw, c, up=True, curve=h, n=n_lashes)

    if badge:
        r = S * (0.15 if small else 0.13)
        # Bottom-right: the open eye's lashes point up, so the top corner is taken.
        bx, by = S - r - S * 0.01, S - r - S * 0.01
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


def app_icon(size: int = 1024):
    """The app icon (Dock/Finder/Launchpad): a white lashed eye on a teal squircle.

    Follows the macOS icon grid: the shape fills ~80% of the canvas with transparent
    margins, and the corner radius is ~22% of the shape.
    """
    from PIL import Image, ImageDraw

    ss = 2
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    m = S * 0.1
    box = [m, m, S - m, S - m]
    # Vertical gradient: deep teal -> lighter teal.
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bot = (18, 120, 100), (64, 190, 160)
    for y in range(S):
        f = y / (S - 1)
        rgb = tuple(int(a + (b - a) * f) for a, b in zip(top, bot, strict=True))
        gd.line([(0, y), (S, y)], fill=rgb + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=(S - 2 * m) * 0.225, fill=255)
    img.paste(grad, (0, 0), mask)
    glyph = render("closed", int(S * 0.62), (255, 255, 255, 255))   # brand mark: rest your eyes
    gx = (S - glyph.width) // 2
    gy = int((S - glyph.height) / 2 + S * 0.02)
    img.alpha_composite(glyph, (gx, gy))
    return img.resize((size, size), Image.LANCZOS)

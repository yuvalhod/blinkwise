"""Personal blink calibration: tune the detector to *your* eyes in about 40 seconds.

The default detector is tuned on several people and sits on a wide plateau, but
some eyes move less when they blink (narrow eyes, heavy lids, a camera far below
the face) and some faces glance at the keyboard in ways that look like blinks.

Calibration asks for a few blinks at known moments, then a few seconds of open eyes
and two looks at the keyboard:

  settle   look at the screen                 (baseline)
  cued     blink each time the dot pulses     (6 known blinks: recall)
  still    keep your eyes open                (any detection is false: precision)
  down     look at your keyboard, then back   (twice; any detection is false)

The frames (numbers only, kept in memory) are re-run through the detector for a
small grid of settings. We keep a personal setting only if it beats the default
on *this* recording: more cued blinks found without adding false ones. Otherwise
we keep the defaults and say so. Nothing is stored except the chosen numbers.
"""

from __future__ import annotations

import dataclasses
import itertools
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .vision.blink import BlinkDetector, BlinkParams
from .vision.features import FrameFeatures


@dataclass(frozen=True)
class Step:
    key: str
    prompt: str
    seconds: float


STEPS = (
    Step("settle", "Look at your screen as usual.", 4.0),
    Step("cued", "Blink once each time the dot pulses.", 16.0),
    Step("still", "Keep your eyes open. Try not to blink.", 6.0),
    Step("down", "Look down at your keyboard when the arrow points down, then back up.", 10.0),
)
CUE_OFFSETS = (1.5, 4.0, 6.5, 9.0, 11.5, 14.0)      # within the cued step
DOWN_WINDOWS = ((1.0, 3.5), (5.5, 8.0))              # within the down step
REACTION = (0.1, 1.6)       # a cued blink lands this long after the cue
CUE_SHOW_S = 0.6            # how long the dot pulses

# The settings worth personalising, each with the values we try. Bounds keep any
# personal value inside the range validated on labelled video.
GRID: Dict[str, Sequence[float]] = {
    "min_prominence": (0.12, 0.15, 0.20, 0.25, 0.30),
    "min_rel_prominence": (0.15, 0.20, 0.25),
    "noise_k": (4.0, 5.0, 6.5),
    "max_pitch_shift": (6.0, 8.0, 11.0),
}
BOUNDS = {k: (min(v), max(v)) for k, v in GRID.items()}


def clean_overrides(raw) -> Dict[str, float]:
    """Only known keys, numeric, within bounds (settings files are user-editable)."""
    out: Dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if k in BOUNDS and isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = BOUNDS[k]
            out[k] = float(min(hi, max(lo, v)))
    return out


def params_from(overrides) -> BlinkParams:
    return dataclasses.replace(BlinkParams(), **clean_overrides(overrides))


def plan() -> List[Tuple[Step, float, float]]:
    out, t = [], 0.0
    for st in STEPS:
        out.append((st, t, t + st.seconds))
        t += st.seconds
    return out


TOTAL_S = sum(s.seconds for s in STEPS) + 1.0     # + detector look-ahead


def cue_times() -> List[float]:
    start = {st.key: a for st, a, _ in plan()}["cued"]
    return [start + c for c in CUE_OFFSETS]


def negative_windows() -> List[Tuple[float, float]]:
    """Where any detected blink is a false one (relative times)."""
    spans = {st.key: (a, b) for st, a, b in plan()}
    still = spans["still"]
    # Leave 1 s at the start of "still" (a cued blink may still be landing) ...
    out = [(still[0] + 1.0, still[1])]
    # ... and count the whole "down" step, where glances happen.
    out.append(spans["down"])
    return out


@dataclass
class Score:
    hits: int
    cues: int
    false: int

    @property
    def value(self) -> float:
        return self.hits - 2.0 * self.false       # a phantom blink costs more than a miss

    def text(self) -> str:
        return f"found {self.hits} of {self.cues} cued blinks, {self.false} false"


def score(frames: Sequence[FrameFeatures], t0: float, params: BlinkParams) -> Score:
    det = BlinkDetector(params)
    times: List[float] = []
    for f in frames:
        b = det.update(f)
        if b is not None:
            times.append(b.t - t0)
    times += [b.t - t0 for b in det.flush()]
    cues = cue_times()
    used = set()
    hits = 0
    for c in cues:
        for i, bt in enumerate(times):
            if i not in used and c + REACTION[0] <= bt <= c + REACTION[1]:
                used.add(i)
                hits += 1
                break
    neg = negative_windows()
    false = sum(1 for bt in times if any(a <= bt < b for a, b in neg))
    return Score(hits, len(cues), false)


@dataclass
class Result:
    ok: bool                         # enough usable data to judge
    default: Optional[Score]
    best: Optional[Score]
    overrides: Dict[str, float] = field(default_factory=dict)
    message: str = ""

    @property
    def improved(self) -> bool:
        return bool(self.overrides)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "improved": self.improved, "overrides": self.overrides,
                "message": self.message,
                "default": self.default.text() if self.default else None,
                "best": self.best.text() if self.best else None}


def fit(frames: Sequence[FrameFeatures], t0: Optional[float] = None) -> Result:
    if not frames:
        return Result(False, None, None, message="No camera frames were recorded.")
    t0 = frames[0].t if t0 is None else t0
    seen = sum(1 for f in frames if f.face)
    if seen < 0.8 * len(frames):
        return Result(False, None, None,
                      message="Your face wasn't visible for much of the test. "
                              "Check the camera position and light, then try again.")
    default = score(frames, t0, BlinkParams())
    base = BlinkParams()
    # Coordinate search: the three depth thresholds together (they interact), then the
    # pitch veto; two rounds. ~50 detector runs (cached) instead of the full 135.
    cache: Dict[Tuple, Score] = {}

    def evaluate(over: Dict[str, float]) -> Score:
        k = tuple(sorted(over.items()))
        if k not in cache:
            cache[k] = score(frames, t0, dataclasses.replace(base, **over))
        return cache[k]

    def key(over: Dict[str, float], sc: Score) -> Tuple[float, float]:
        # Higher score first; on ties, the setting closest to the defaults.
        dist = sum(abs(v - getattr(base, k)) / (BOUNDS[k][1] - BOUNDS[k][0]) for k, v in over.items())
        return (sc.value - 10.0 * max(0, sc.false - default.false), -dist)

    groups = [("min_prominence", "min_rel_prominence", "noise_k"), ("max_pitch_shift",)]
    cur: Dict[str, float] = {}
    cur_key = key(cur, default)
    for _ in range(2):
        for g in groups:
            for combo in itertools.product(*(GRID[k] for k in g)):
                cand = {**cur, **dict(zip(g, combo, strict=True))}
                cand = {k: v for k, v in cand.items() if v != getattr(base, k)}
                ck = key(cand, evaluate(cand))
                if ck > cur_key:
                    cur, cur_key = cand, ck
    best = evaluate(cur) if cur else default
    best_over = cur if (best.value > default.value and best.false <= default.false) else {}
    if not best_over:
        best = default
    if default.hits < 2 and best.hits < 2:
        return Result(False, default, best, message=(
            f"Blinkwise only {default.text()}. That usually means the camera can't see your "
            "eyes well enough (light, angle or glasses glare). Fix the setup and try again."))
    if best_over:
        msg = (f"Personal settings found: {best.text()} "
               f"(default settings {default.text()}).")
    else:
        msg = (f"The default settings already work well for you: {default.text()}.")
    return Result(True, default, best, {k: float(v) for k, v in best_over.items()}, msg)


class Session:
    """Live state machine for the dashboard / CLI. Feed frames; read `state()`."""

    def __init__(self, max_frames: int = 3000, background: bool = True):
        self.t0: Optional[float] = None
        self.frames: List[FrameFeatures] = []
        self.max_frames = max_frames
        self.result: Optional[Result] = None
        self.background = background
        self._fitting = False
        self._now = 0.0

    def feed(self, f: FrameFeatures) -> None:
        if self.result is not None or self._fitting:
            return
        if self.t0 is None:
            self.t0 = f.t
        self._now = f.t - self.t0
        if len(self.frames) < self.max_frames:
            self.frames.append(f)
        if self._now >= TOTAL_S:
            self._fitting = True
            if self.background:      # a few seconds of CPU: keep the vision loop running
                threading.Thread(target=self._fit, name="calibration", daemon=True).start()
            else:
                self._fit()

    def _fit(self) -> None:
        frames, self.frames = self.frames, []          # done with the recording
        try:
            res = fit(frames, self.t0)
        except Exception as e:                          # never take the app down
            res = Result(False, None, None, message=f"Calibration failed: {e}")
        self.result = res
        self._fitting = False

    @property
    def done(self) -> bool:
        return self.result is not None

    def state(self) -> dict:
        if self.result is not None:
            return {"done": True, "progress": 1.0, **self.result.as_dict()}
        if self._fitting:
            return {"done": False, "step": "analyzing", "prompt": "Analysing...", "cue": False,
                    "look_down": False, "progress": 1.0}
        rel = self._now
        step, a = STEPS[-1], 0.0
        for st, s0, s1 in plan():
            if s0 <= rel < s1:
                step, a = st, s0
                break
        cue = any(c <= rel < c + CUE_SHOW_S for c in cue_times())
        down = step.key == "down" and any(a + w0 <= rel < a + w1 for w0, w1 in DOWN_WINDOWS)
        return {"done": False, "step": step.key, "prompt": step.prompt, "cue": cue,
                "look_down": down, "progress": round(min(1.0, rel / TOTAL_S), 3)}

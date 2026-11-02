"""A 30-second guided check that blink detection works on *your* face and camera.

Lab validation can't cover every webcam, room and pair of glasses, so every
user can verify the essentials themselves:

  settle  look at the screen normally   -> frame rate, face size, light, jitter
  blink   blink 5 times                 -> did we see about 5?
  still   keep your eyes open           -> did we hallucinate any? (false positives)
  turn    look left or right and back   -> is head tracking working?

The runner is pure (features in, report out) so it's tested with synthetic
frames and works on recorded video as well as a live camera.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Tuple

from .vision.blink import Blink, BlinkDetector
from .vision.features import FrameFeatures
from .vision.quality import Quality, assess


@dataclass(frozen=True)
class Phase:
    key: str
    prompt: str
    seconds: float


PHASES = (
    Phase("settle", "Look at your screen normally.", 6.0),
    Phase("blink", "Blink 5 times, at your normal speed.", 8.0),
    Phase("still", "Now keep your eyes open and try not to blink.", 6.0),
    Phase("turn", "Turn your head to look at something to your left or right, then back.", 6.0),
)
LEAD_IN_S = 2.0     # pause before each phase so the user can read the prompt
EXPECTED_BLINKS = 5


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    tip: str = ""


@dataclass
class Report:
    checks: List[Check] = field(default_factory=list)
    quality: Optional[Quality] = None
    blinks_in_blink_phase: int = 0
    blinks_in_still_phase: int = 0
    fps: float = 0.0
    distance_cm: Optional[float] = None

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def lines(self) -> List[str]:
        out = []
        for c in self.checks:
            out.append(f"  [{'ok' if c.ok else '!!'}] {c.name}: {c.detail}")
            if not c.ok and c.tip:
                out.append(f"       -> {c.tip}")
        verdict = ("Everything looks good. Blinkwise can track your eyes reliably."
                   if self.passed else
                   "Some checks failed. Blinkwise will still run, but follow the tips above "
                   "for accurate results.")
        return out + ["", verdict]


def schedule(phases=PHASES, lead_in: float = LEAD_IN_S) -> List[Tuple[Phase, float, float]]:
    """(phase, start, end) offsets in seconds from the start of the test."""
    out, t = [], 0.0
    for ph in phases:
        t += lead_in
        out.append((ph, t, t + ph.seconds))
        t += ph.seconds
    return out


def total_seconds(phases=PHASES, lead_in: float = LEAD_IN_S) -> float:
    return schedule(phases, lead_in)[-1][2] + 0.8   # + detector look-ahead


def run_selftest(frames: Iterable[FrameFeatures],
                 on_prompt: Optional[Callable[[Phase, int, int], None]] = None,
                 phases=PHASES, lead_in: float = LEAD_IN_S) -> Report:
    plan = schedule(phases, lead_in)
    end_all = total_seconds(phases, lead_in)
    det = BlinkDetector()
    blinks: List[Blink] = []
    t0: Optional[float] = None
    announced = -1
    seen = faces = 0
    yaws: List[float] = []
    settle: List[FrameFeatures] = []

    def phase_at(rel: float) -> Optional[Phase]:
        for ph, a, b in plan:
            if a <= rel < b:
                return ph
        return None

    for f in frames:
        if t0 is None:
            t0 = f.t
        rel = f.t - t0
        # Announce the next phase as its lead-in begins.
        for i, (ph, a, _) in enumerate(plan):
            if i > announced and rel >= a - lead_in:
                announced = i
                if on_prompt:
                    on_prompt(ph, i + 1, len(plan))
        b = det.update(f)
        if b is not None:
            blinks.append(b)
        seen += 1
        faces += int(f.face)
        ph = phase_at(rel)
        if ph is not None and f.face:
            if ph.key == "settle":
                settle.append(f)
            elif ph.key == "turn":
                yaws.append(f.yaw)
        if rel >= end_all:
            break
    blinks += det.flush()

    rep = Report(fps=det.fps)

    def count(key: str) -> int:
        for ph, a, b in plan:
            if ph.key == key:
                # A blink belongs to the phase it happened in (half a second of grace at the end).
                return sum(1 for bl in blinks if a <= bl.t - (t0 or 0) < b + 0.5)
        return 0

    rep.blinks_in_blink_phase = count("blink")
    rep.blinks_in_still_phase = count("still")
    face_pct = 100.0 * faces / max(seen, 1)
    rep.checks.append(Check("Face found", face_pct >= 90, f"in {face_pct:.0f}% of frames",
                            "Centre your face in the camera and make sure it's well lit."))
    face_px = statistics.median([f.face_px for f in settle if f.face_px]) if any(
        f.face_px for f in settle) else None
    lum = statistics.median([f.luminance for f in settle if f.luminance is not None]) if any(
        f.luminance is not None for f in settle) else None
    dists = [f.distance_cm for f in settle if f.distance_cm]
    rep.distance_cm = statistics.median(dists) if dists else None
    q = rep.quality = assess(det.fps, face_px, lum, det.noise)
    rep.checks.append(Check(
        "Tracking quality", q.level in ("good", "fair"),
        q.level + (f" ({'; '.join(q.reasons)})" if q.reasons else ""), " ".join(q.tips)))
    rep.checks.append(Check(
        "Frame rate", det.fps >= 18,
        f"{det.fps:.0f} fps" + ("" if det.fps >= 20 else " (blink completeness needs 20+)"),
        "Add light: many webcams drop to 15 fps or less in dim rooms."))
    n = rep.blinks_in_blink_phase
    rep.checks.append(Check(
        "Detects your blinks", EXPECTED_BLINKS - 1 <= n <= EXPECTED_BLINKS + 2,
        f"saw {n} of the {EXPECTED_BLINKS} blinks you were asked for",
        "If it saw fewer: improve lighting and face the camera. If you have heavy-framed "
        "glasses, try a slightly different angle to avoid frame edges over your eyes."))
    fp = rep.blinks_in_still_phase
    rep.checks.append(Check(
        "No phantom blinks", fp <= 1,
        f"{fp} blink{'s' if fp != 1 else ''} detected while you held your eyes open",
        "Phantom blinks usually mean a jittery image: add light and keep the camera steady."))
    turn = (max(yaws) - min(yaws)) if len(yaws) > 5 else 0.0
    rep.checks.append(Check("Head tracking", turn >= 15, f"followed a {turn:.0f} degree head turn",
                            "Make sure you turned your head, and that your whole face is in view."))
    return rep

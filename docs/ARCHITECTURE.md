# Architecture

```
src/blinkwise/
  vision/            pixels -> numbers
    camera.py        FrameSource: webcam or video file
    tracker.py       MediaPipe Face Landmarker -> FrameFeatures (the only code that sees pixels)
    geometry.py      EAR, head pose, iris distance (pure functions)
    features.py      FrameFeatures dataclass
    blink.py         BlinkDetector (online, ~0.7 s latency)
    attention.py     screen zones from head yaw
    evaluate.py      scoring against hand-labelled ground truth
  core/              numbers -> decisions (no I/O, no clock: fully testable)
    engine.py        Engine.step(FrameFeatures) -> events
    metrics.py       rolling blink stats over observed time
    breaks.py        BreakScheduler
    coach.py         evidence-based rules, cooldowns, anti-nag
    simulate.py      synthetic users with ground truth (tests + `blinkwise demo`)
    storage.py       SQLite per-minute history
    events.py        event dataclasses
  ui/
    overlay.py       Tk blink cue, break card, toast
    notify.py        native notifications (macOS/Windows/Linux)
    dashboard.py     local HTTP server + JSON API
    static/index.html
  app.py             threads + wiring
  cli.py             `blinkwise ...`
  research.py        references and reference values
  config.py          settings and data folder
```

## Threads

* **main**: the Tk event loop (macOS requires GUI on the main thread). It polls an event queue every 50 ms.
* **vision worker**: camera -> tracker -> engine. The engine is single-threaded; the UI and dashboard send it commands through a queue.
* **http**: the dashboard reads a snapshot the worker publishes at 5 Hz.

## Blink detector

1. **Per-eye open baseline**: the 80th percentile of EAR over the last 3 s. Openness `o = EAR / baseline`, so 1.0 means open for *this* person in *this* head pose.
2. **Fusion**: the two eyes are weighted by apparent width², because the far eye of a turned head is foreshortened and noisier. Frames with |yaw| > 40° are skipped.
3. **Peak detection with look-ahead**: each sample is judged once 0.7 s of future signal exists. A blink is a sample that:
   * is the lowest point within ±0.15 s;
   * has prominence ≥ 0.20 (absolute) and ≥ 25% (relative), measured against the *lower* of the maximum openness in the 0.5 s before and the 0.7 s after. Requiring both sides is what rejects slow drifts and sustained downward gaze;
   * has a half-prominence width ≤ 1.0 s (≤ 0.5 s is a normal blink, longer is flagged "long");
   * doesn't coincide with a head-pitch shift > 8° *unless* the closure is deep (≥ 0.6). This rejects keyboard glances, where the lid follows the gaze, but keeps blinks that ride on head movements;
   * doesn't overlap the previous blink.
4. **Completeness**: closure = prominence / reference. Reported only at ≥ 20 fps.

Parameters were chosen on the labelled video and simulations, and sit on a wide plateau: on the real video, precision stays at 1.00 for any prominence threshold from 0.15 to 0.30 (`scripts/eval_blinks.py`).

## Robustness

* **User lock** (`vision/tracker.py: UserLock`): MediaPipe tracks up to 3 faces. Within 10 s of last seeing the user we follow the face nearest their last position, and if only *other* people are visible we report "no user" rather than adopting them. On a two-person video this cut identity switches from 3 to 0.
* **Noise adaptation** (`vision/blink.py`): a robust running estimate of frame-to-frame jitter raises the minimum dip depth to 5 sigma, and a median-of-3 filter runs at 20 fps or more. With 3x simulated sensor noise, false blinks fell from 442/hour to 1/hour.
* **Low light** (`vision/enhance.py`): dark frames get a gamma lift plus a 5x5 blur before landmarking (1.5 ms). Measured alternatives, including CLAHE, bilateral filtering and MediaPipe's own eyeBlink blendshape, did worse; see the module docstring.
* **Quality gate** (`vision/quality.py`): fps, face size, lighting and jitter give a good/fair/poor grade. "Poor" pauses blink-based coaching and tells the user how to fix it.
* **Eye-in-head gaze** (`geometry.eye_in_head_yaw`) is computed but *not* used for screen zones. At webcam resolution one pixel of iris error is about 6 degrees, and reading across a wide monitor sweeps the eyes +/-20 degrees.

## Menu bar

`ui/icon.py` draws the icon procedurally: a closed eye with lashes, plus open and half frames for the blink animation. It renders black + alpha so macOS can use it as a template image. `ui/menu.py` builds the dropdown as plain data, and `ui/tray.py` renders it with pystray. On macOS the tray owns the main thread and updates are marshalled with `AppHelper.callAfter`; elsewhere it runs in a background thread next to Tk. `scripts/render_menubar_mock.py` renders a design mock-up from the same code.

## Adding a coaching rule

1. Write `rule_xxx(ctx, settings) -> Optional[Suggestion]` in `core/coach.py`. Keep it pure.
2. Register it in `Coach.__post_init__` with a cooldown.
3. Cite a reference from `research.py` (add one if needed; the tests check that keys exist).
4. Add a test in `tests/test_coach.py` covering both the firing and the non-firing case.

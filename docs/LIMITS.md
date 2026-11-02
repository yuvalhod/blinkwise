# When Blinkwise works, and when it doesn't

Measured, not guessed. Every number here comes from real webcam video run
through the full pipeline (`scripts/stress_matrix.py`, `scripts/eval_blinks.py`)
against hand-labelled blinks. The guiding rule: **when Blinkwise can't see well, it
says so and stops giving blink advice, instead of giving you wrong numbers.**

## Conditions (held-out real video, 27 labelled blinks)

| Condition | Precision | Recall | What the app does |
|---|---|---|---|
| Normal webcam, face the camera | 1.00 | 1.00 | coaches normally |
| Blurry / low-resolution camera | 0.96 | 0.96 | coaches normally |
| Sitting far away (face 60% size, ~68 px) | 1.00 | 0.96 | coaches (face-following zoom) |
| Very far (face 40% size, ~46 px) | 1.00 | 0.96 | coaches (zoom finds the face by searching tiles) |
| Webcam at 6 fps | 1.00 | 0.93 | coaches; blink completeness needs 20+ fps |
| Motion blur | 1.00 | 0.96 | coaches normally |
| Bright window behind you | 1.00 | 0.96 | coaches normally |
| Hand / object over one eye | 1.00 | 0.96 | coaches (uses the visible eye) |
| Heavy video compression | 0.80 | 0.89 | **pauses blink advice** (jittery tracking) |
| Dim room with sensor noise | 1.00 | 0.56 | **pauses blink advice** (face is very dark) |
| Glare covering glasses lenses | 1.00 | 0.04 | **pauses blink advice** (can't see your eyes) |
| Sunglasses | - | 0.00 | **pauses blink advice** (can't see your eyes) |

Before the fixes in this release, sunglasses and glare produced mostly *invented*
blinks (precision 0.19-0.33), and a face at 40% size wasn't found at all.

## Head angle

How noisy the eye signal is, relative to facing the camera (two real videos):

| Head turned from the camera | Signal available | Noise |
|---|---|---|
| 0-10 degrees | 99% | 1x |
| 10-20 degrees | 94% | 1.6x |
| 20-30 degrees | 95% | 2x |
| 30-40 degrees | 80% | 9x |
| more than 40 degrees | paused on purpose | - |

Looking far down (15-40 degrees) roughly doubles the noise. **Put the camera on top of
the screen you look at most.** The setup guide (`/setup`, opened on first run and from
"Check camera setup" in the menu) measures this live and tells you which way to move it.

## What happens when...

* **You leave or turn fully away:** counted as away. That time counts toward your break,
  the stare timer restarts, and the camera drops to 2 frames per second.
* **Your eyes are hidden but your face isn't** (sunglasses, glare): detected from the
  pixels (iris contrast), not trusted from the landmarks. Blink statistics pause and that
  time doesn't count against your blink rate.
* **Someone else is in view:** Blinkwise follows the person closest to the screen and
  never switches to a bystander while you briefly look away.
* **You glance at your keyboard or phone:** the lids follow your gaze down, which looks
  like a blink; a head-pitch check rejects these (2 false blinks in 80 simulated minutes of
  constant glancing, versus 33 without it). Sustained looking down counts as device time.
* **The camera is noisy:** the minimum blink depth adapts to measured jitter (false blinks
  at 3x noise: 442/hour before, 1/hour now).

## Known gaps

* Labelled real data is still small: two people, 12 fps. Complete-vs-partial blinks are
  validated on simulation only (real 30 fps labelled footage wasn't available).
* Glasses with thick frames that cross the eyes, and very dark rooms, remain hard.
* A face at less than ~40 px can't be tracked; the setup guide asks you to sit closer.

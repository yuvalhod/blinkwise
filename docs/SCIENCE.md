# The science behind Blinkwise

Blinkwise only gives advice it can trace to evidence, and it says how strong that evidence is. Every number below lives in `src/blinkwise/research.py` (references) or `src/blinkwise/config.py` (thresholds).

## 1. Screens suppress blinking

* Relaxed blink rate is roughly 15-20/min (higher in conversation).
* During screen work it falls sharply: an average of about five-fold in Patel et al. (1991), and from roughly 22 to 7/min in the widely cited Tsubota & Nakamori (1993) report.
* The cause is mostly attention: concentrating suppresses the blink reflex. That's why games, code and spreadsheets are the worst, and why Blinkwise compares blink rate *per screen*.

**What Blinkwise does:** measures your rate over a rolling 5-minute window of *observed* time, so walking away doesn't count against you. It warns below 10/min (default) and treats below 6/min as high priority. These cut-offs are product judgement, anchored to the published normal and on-screen ranges; there is no clinical threshold for "too low".

## 2. Blink *quality* matters as much as quantity

* Portello, Rosenfield & Chu (2013): eye-strain symptoms correlated with the percentage of **incomplete** blinks. Raising blink rate with an audible tone did *not* reduce symptoms.
* A partial blink doesn't spread tears over the lower cornea, which then dries.

**What Blinkwise does:** measures closure depth for each blink relative to your own open eye, and calls a blink "complete" if the lids close at least 60% of the way. This needs 20 fps or more; below that the bottom of a ~100 ms blink can fall between frames, so we say "not available" rather than guess. It suggests blinking exercises if more than 40% of blinks are partial.

**Caveat:** webcam-measured completeness isn't the same as the slit-lamp or high-speed-video measurements used in studies. Treat the percentage as a personal trend, not a clinical value.

## 3. Prompting blinks helps

* Nosch et al. (2015): a "blink blink" animation that asked users to blink twice raised blink rate by about 6.8/min and reduced dry-eye symptoms more than placebo (1-week crossover, n=24). The placebo group also improved, so the specific effect is modest.

**What Blinkwise does:** after 10 s without a blink (configurable), a small animated eye at the top of the screen blinks twice and fades. It's deliberately small and doesn't steal focus.

## 4. Breaks: 20-20-20 and hourly breaks

* 20-20-20 (every 20 min, look 20 ft / 6 m away for 20 s) is recommended by optometry bodies. Talens-Estarelles et al. (2023) tested it with webcam software similar to Blinkwise: symptoms of digital eye strain and dry eye fell over two weeks, but the effect **faded a week after the reminders stopped**. That argues for a tool people keep running.
* Galinsky et al. (2000, NIOSH): adding short 5-minute breaks every hour reduced eye soreness and discomfort without hurting productivity.

**What Blinkwise does:** micro breaks every 20 min of *screen time* and a 5-minute break every 60 min. Looking away or leaving the desk long enough counts as the break, so you aren't interrupted after you've already rested. When your 10-minute blink rate is low, micro breaks come 25% sooner. Breaks can always be skipped; missed ones snooze for 5 minutes instead of nagging.

## 5. Blinking exercises

* Kim et al. (2020): a 10-second blinking exercise every 20 minutes for four weeks improved dry-eye symptoms (pilot study).
* Aston University (2025): 15 "close - squeeze - open" cycles three times a day reduced symptoms *and* the number of incomplete blinks; benefits faded about two weeks after stopping.

**What Blinkwise does:** suggests the exercise during long breaks and when partial blinks are frequent.

## 5b. Drowsiness: PERCLOS

* Dinges & Grace (1998, US FHWA): the proportion of time the eyes are at least 80% closed (PERCLOS) tracked lapses of attention better than other eye and head measures. It's the standard camera-based drowsiness metric.

**What Blinkwise does:** measures PERCLOS over 5 minutes. Closures longer than 5 s (deliberately resting your eyes) and time during breaks don't count. At 15% or more it suggests a real break. The 15% level is a commonly used alert threshold, not a medical cut-off.

## 6. Screen distance and height

* AOA guidance: about 20-28 inches (50-70 cm) from the eyes, with the screen centre 15-20 degrees below eye level.
* Tsubota & Nakamori (1995): looking up exposes more of the eye's surface and increases tear evaporation.

**What Blinkwise does:** estimates distance from your iris diameter (the horizontal visible iris is about 11.7 ± 0.5 mm in adults) with pinhole geometry. Accuracy depends on knowing your camera's focal length; the default assumes a 60° field of view, and `blinkwise calibrate` fixes it. Head pitch is used as a rough "screen too high" heuristic, which assumes the camera sits on top of your main screen.

## 7. Multiple screens

There is little direct research on multi-monitor eye strain. The advice Blinkwise gives is ergonomic common sense consistent with the guidance above: put the screen you use most directly in front of you; keep screens at the same height and distance so your eyes don't refocus on every switch; avoid large head turns. Blinkwise reports these as **insights**, not warnings, unless a screen needs more than a 35° head turn or your main screen is well off-centre.

## 8. Children and teens

* He et al. (2015, JAMA, randomised trial): an extra 40 minutes outdoors each school day reduced 3-year myopia incidence from 39.5% to 30.4%.

**What Blinkwise does:** with `profile=young`, it adds a daily reminder about outdoor time.

## 9. The weekly check-in

Three questions, answered Never / Sometimes / Often / Almost always: dry or gritty eyes, tired or strained eyes, blurry vision after screen use. These are the three symptom groups that screen eye-strain questionnaires keep returning to (the OSDI for ocular surface symptoms; the CVS-Q for computer vision syndrome). The wording is ours and the questions are not a validated instrument, so the score is a personal trend, not a diagnosis. Blinkwise suggests an eye-care professional when one symptom is "almost always" present, or the total (0-9) is 6 or more two weeks in a row, because persistent symptoms can have causes no habit fixes (dry eye disease, an outdated prescription, binocular vision problems).

## Known limitations

* Validated so far on one labelled real video plus simulations. More real-world labelled data (glasses, low light, darker skin tones, children) is needed and very welcome.
* Webcams below 20 fps can count blinks but not judge their completeness.
* Thick-framed glasses, strong backlight and extreme head angles (beyond 40° of yaw) reduce accuracy; Blinkwise pauses detection rather than guessing.

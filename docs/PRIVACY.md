# Privacy

Blinkwise points a camera at your face all day, so privacy isn't a feature. It's the precondition.

## What happens to camera frames

1. A frame is read from the camera into memory.
2. MediaPipe finds facial landmarks in it, on your CPU.
3. A dozen numbers are computed in memory (`FrameFeatures`: eye openness, head angles, estimated distance, face brightness). Most are used only for that moment and never written down; see the table below for the few per-minute totals that are kept.
4. The frame is discarded. It is never written to disk, logged, cached or sent anywhere.

The rest of the app only ever sees those numbers. You can check this in the code: `vision/tracker.py` is the only module that touches pixels.

## What is stored (and nothing else)

One SQLite file in your user data folder, plus your settings. Each item is kept only
because a feature reads it:

| Stored, per minute | Used for |
|---|---|
| Seconds your eyes were measurable, blink counts (full / partial / long) | blink rate, full-blink % |
| Longest stare, count of 20 s+ stares | stare insights |
| Median viewing distance (cm) | "too close" tip, leaning-in pattern |
| Number of screens in use | multi-screen insight |
| Seconds on your computer screen / looking down at another device, switches | screen time, phone time, switching between them |
| Minutes of continuous use | your blink-drop pattern and break interval |

Plus: break outcomes (taken / skipped), your settings, and small marker files (first-run
notice shown, date of the last daily summary, date and result of the last update check).
If you tune blink detection to your eyes, the ~40 s of measurements it uses stay in memory
and are dropped right after; only up to four detector numbers are saved in your settings.

**Not stored, ever:** images or video, face landmarks or measurements that could identify
you, head angles, the suggestions you were shown, or anything about other people in view
(Blinkwise only keeps a count of faces, in memory). Older versions stored head angles,
face brightness and a log of suggestions; upgrading removes those columns and vacuums the
file so they are physically gone.

**Retention:** history older than 3 months is deleted automatically (choose 1 week, 1
month, 3 months or 1 year in Settings > Your data). **Export** downloads everything as
JSON; **Delete** erases it all. `blinkwise wipe` does the same from the terminal, and
`store_history=false` keeps nothing at all.

**Logs:** the Mac app writes warnings only to `~/Library/Logs/Blinkwise.log`, restarted
when it passes 1 MB. No activity or health data goes into logs.

Nothing leaves your device and nothing is sent to us, so there's no account and no data
for us to hold. Organisations (schools, employers) that deploy Blinkwise on other people's
computers should still check their own obligations; the design keeps that simple, and it
can be verified in the code: storage is `src/blinkwise/core/storage.py`, and the only
network access is the one-time model download. This is not legal advice.

## Network

* **One-time model download** (3.7 MB) from `storage.googleapis.com` (Google's official MediaPipe model bucket), verified against a pinned SHA-256. To avoid even this, download the file yourself and set `BLINKWISE_MODEL=/path/to/face_landmarker.task`.
* **Daily update check** (you can turn it off: Settings > Check for updates daily, or `blinkwise config check_updates=false`). Once a day Blinkwise asks GitHub for the project's latest release number: an anonymous GET of `api.github.com/repos/blinkwise/blinkwise/releases/latest` with no identifiers, settings or usage data. GitHub sees your IP address, as with any web request. If there's a newer version you'll see a link; nothing is downloaded or installed automatically.
* **Nothing else.** No telemetry, analytics or accounts. The dashboard page loads no external scripts, fonts or images.

## The local dashboard

* Listens on `127.0.0.1` only, so it can't be reached from your network.
* Rejects requests whose `Host` header isn't localhost (protects against DNS-rebinding attacks from websites you visit).
* Actions (pause, start a break) need a random token that exists only in the page Blinkwise serves, so other websites can't trigger them.
* Sends a strict Content-Security-Policy.

## Camera control

"Pause camera" in the dashboard releases the device, so your camera's light turns off. Quitting the app (Ctrl+C) releases it too. When nobody is in front of the camera for a minute, Blinkwise drops to 2 frames per second.

## Battery and video calls

To save battery and stay out of the way in calls, Blinkwise checks every 5 seconds, on your
device only: whether you're on battery, whether a meeting-only process is running (for
example Zoom's `CptHost`), and on Windows/Linux whether another program has the webcam open.
It doesn't record which apps you run; only "in a call: yes/no" is kept in memory, and it's
never stored or sent. Set "In video calls" to "No change" in Settings to switch this off.

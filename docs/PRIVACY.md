# Privacy

Blinkwise points a camera at your face all day, so privacy isn't a feature. It's the precondition.

## What happens to camera frames

1. A frame is read from the camera into memory.
2. MediaPipe finds facial landmarks in it, on your CPU.
3. A dozen numbers are computed (`FrameFeatures`: eye openness, head angles, estimated distance, face brightness).
4. The frame is discarded. It is never written to disk, logged, cached or sent anywhere.

The rest of the app only ever sees those numbers. You can check this in the code: `vision/tracker.py` is the only module that touches pixels.

## What is stored

A SQLite file in your user data folder, holding one row per minute: blink counts, observed seconds, longest stare, median distance and head angles, number of screens in use, plus break outcomes and suggestion titles. Run `blinkwise doctor` to see where it is; `blinkwise wipe` deletes it. Set `blinkwise config store_history=false` to keep nothing at all.

## Network

* **One-time model download** (3.7 MB) from `storage.googleapis.com` (Google's official MediaPipe model bucket), verified against a pinned SHA-256. To avoid even this, download the file yourself and set `BLINKWISE_MODEL=/path/to/face_landmarker.task`.
* **Nothing else.** No telemetry, analytics, accounts or update checks. The dashboard page loads no external scripts, fonts or images.

## The local dashboard

* Listens on `127.0.0.1` only, so it can't be reached from your network.
* Rejects requests whose `Host` header isn't localhost (protects against DNS-rebinding attacks from websites you visit).
* Actions (pause, start a break) need a random token that exists only in the page Blinkwise serves, so other websites can't trigger them.
* Sends a strict Content-Security-Policy.

## Camera control

"Pause camera" in the dashboard releases the device, so your camera's light turns off. Quitting the app (Ctrl+C) releases it too. When nobody is in front of the camera for a minute, Blinkwise drops to 2 frames per second.

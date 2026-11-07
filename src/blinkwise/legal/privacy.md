# Privacy Policy

Version 2026-11-07. This policy covers the Blinkwise app and the optional Blinkwise Family
service. Plain summary: **Blinkwise processes camera images only on your own computer,
never stores or sends them, and keeps a small set of numbers on your computer that you can
export or delete at any time.**

## 1. Who is responsible

* **The Blinkwise app** runs entirely on your device. The Blinkwise project does not
  receive, see or hold any data from the app. For data on your device, you are in control.
* **Blinkwise Family** (optional) is a server run by an operator: the person or
  organisation whose server address you connect to. That operator is the data controller for
  the data described in section 5 and is responsible for publishing their contact details and
  any additional terms. If you run your own server, that is you.

Contact for this policy: the operator's published contact, or, for the open-source project,
the issue tracker of the repository you installed from.

## 2. What the app processes on your device

* **Camera images.** Each frame is analysed in memory, on your computer, to estimate a
  handful of numbers (eye openness, head angle, distance from the screen, lighting). The frame
  is then discarded. Images and video are never saved, logged or sent anywhere. No face
  recognition or identification is performed; Blinkwise does not know who you are.
* **Stored numbers.** Per-minute totals (for example blinks, seconds of screen time, median
  viewing distance), break outcomes, your settings, and, if you answer it, a weekly three-
  question eye check-in (three scores from 0 to 3). The full list is in docs/PRIVACY.md.
* **System signals.** Whether your computer is on battery and whether a video-call app is
  running, checked in memory to save power and stay quiet in calls. Not stored or sent.
* **Not collected:** your name, email, account, location, contacts, browsing, app usage,
  images of you, or anything about other people in view.

## 3. What leaves your device

Nothing, unless one of these applies:

| What | When | Sent to | Contains |
|---|---|---|---|
| Face model download | once, at first start | Google's model storage | an ordinary file download |
| Update check | once a day, can be turned off | GitHub | an anonymous request for the latest version number |
| Family sharing | only after you enter a parent's pairing code | the parent's Family server | weekly totals listed in section 5 |

As with any web request, the receiving server sees your IP address. Blinkwise adds no
identifiers, tracking or analytics.

## 4. Your choices and rights

* **See everything:** Settings > Your data > Export downloads all stored data as JSON.
* **Delete everything:** Settings > Your data > Delete, or `blinkwise wipe`.
* **Keep less:** choose how long history is kept (1 week to 1 year), or turn history off.
* **Pause:** the camera can be paused at any time from the menu bar; its light turns off.
* **Uninstall:** removing the app and its data folder removes all data it stored.

Because the app's data never leaves your device, requests about it are fulfilled by these
controls. For Family data, see section 5.

## 5. Blinkwise Family (optional)

**Parents** sign in with an email link. The operator stores the parent's email address, the
name or nickname the parent chooses for each child, and the weekly totals each paired
computer sends: days used, average screen time, phone time, blink rate, share of full blinks,
eye breaks taken, viewing distance, strained-posture minutes, and, only if the child turns it
on, the weekly check-in score. Never images, video, per-minute data, location or the
child's email or account.

* **Children and parental consent.** Sharing starts only when a parent or legal guardian
  creates a pairing code and confirms they are the child's parent or guardian and consent.
  The child's computer shows that sharing is on and exactly what is shared. The parent can
  remove a child at any time; the child (with the parent PIN, if one is set) can stop
  sharing, which deletes that child's data on the server.
* **Purpose and legal basis.** To show the parent their child's weekly screen and eye habits
  and, if the parent chooses, email them weekly. Basis: the parent's consent (and, where
  applicable, performance of the service the parent signed up for).
* **Retention.** Weekly totals are kept for 26 weeks. Deleting the account deletes the
  parent's email, children and all their weekly totals.
* **Rights.** Parents can view, export (by viewing), correct names, delete children and
  delete their account from the Family page. Under laws such as the GDPR and UK GDPR you may
  also have rights to access, correct, erase, restrict and object, and to complain to your data
  protection authority. Contact the operator.
* **Processors.** The operator uses a hosting provider and an email provider to run the
  service; they process data only on the operator's instructions.

## 6. Security

Images are never stored. The local dashboard is reachable only from your own computer and
rejects requests from other websites. The Family service uses HTTPS, single-use sign-in
links, hashed tokens, rate limits and cross-site request protection. No system is perfectly
secure; report problems through the repository's issue tracker.

## 7. Children

Blinkwise can be used by children with a parent's or guardian's involvement (kids mode). The
app itself collects no personal information from children; it keeps numbers on the device.
The Family service collects data about a child only with verified parental action and
consent, as described in section 5. Parents should supervise use by children under 13.

## 8. Not a medical device

See the Terms of Use. Blinkwise's numbers are estimates for building habits, not medical
measurements.

## 9. Changes

If this policy changes, the new version is shipped with the app and the app asks you to
review it before the camera turns on again.

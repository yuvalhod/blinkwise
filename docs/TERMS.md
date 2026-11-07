# Terms of Use and Medical Disclaimer

The Terms of Use are [src/blinkwise/legal/terms.md](../src/blinkwise/legal/terms.md). The app
shows them (Dashboard > Terms, and the setup guide) and asks you to accept them once before
the camera turns on; the Family site shows them at /terms and asks parents to accept them
when signing in.

Summary: Blinkwise is a general wellness and habit tool, **not a medical device**. It doesn't
diagnose, treat or prevent anything, its webcam estimates can be wrong, and it must never be
used for safety decisions such as whether you're alert enough to drive. See an eye-care
professional for symptoms. The software is MIT-licensed and provided without warranty.

## For maintainers

* Bump `TERMS_VERSION` in `src/blinkwise/legal/__init__.py` whenever either document changes
  materially; every user is then asked to review again before the camera turns back on.
* These documents were written to be careful and accurate, but they are **not legal advice**.
  Before a public launch, and before anyone runs a Family server for other people, have a
  lawyer review them for your jurisdictions (for example COPPA and state privacy laws in the
  US, GDPR / UK GDPR and the UK Children's Code in Europe), fill in the operator's contact
  details, and check the app's wellness claims against FDA general-wellness guidance and EU
  medical-device rules.

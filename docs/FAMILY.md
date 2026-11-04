# Kids mode and family sharing

## Kids mode (on the child's computer)

Settings > Notifications > Profile > Child / teen.

* Friendlier break prompts ("Find the farthest thing you can see and count to 20").
* An outdoor-time reminder after an hour of screen time (outdoor light is the best-supported way to slow myopia in children; see [SCIENCE.md](SCIENCE.md)).
* **Parent PIN** (Settings > Family > Parent PIN): locks settings, deleting history and stopping sharing. It stops casual changes. It is not a security boundary against a determined teenager with access to the settings file, and the parent will see days with no data.

The child can always pause the camera and choose whether their weekly eye check-in score is shared.

## Family sharing

Nothing is shared until someone enters a parent's pairing code. Then:

| | |
|---|---|
| **What's sent** | Weekly totals only: days used, screen and phone time a day, blink rate, full-blink %, breaks taken, viewing distance, strained-posture minutes, and (only if the child chooses) the weekly check-in score. The exact list is `src/blinkwise/family/payload.py`; the server rejects any other field. |
| **Never sent** | Video, images, face data, per-minute history, app names, location. |
| **How often** | At most every 6 hours, last week's and this week's totals. |
| **Transparency** | The child's menu bar says "Sharing weekly totals with a parent". The dashboard shows "What's shared", value by value, before connecting and while connected. |
| **Stopping** | The child (with the PIN, if one is set) or the parent can disconnect. When the child stops, their data on the server is deleted and the parent sees that sharing stopped. |

### Parent accounts

Parents sign in with a magic link sent by email (no passwords). They can add children (up to 10), see each child's latest weeks next to the week before, turn the Monday-morning email on or off, and delete their account and all data.

## Running the server

The server is `blinkwise family-server`: Python standard library and SQLite, no other dependencies.

```bash
blinkwise family-server --host 0.0.0.0 --port 8790 --public-url https://family.example.org
```

Children's apps find it through the address typed when connecting, or `BLINKWISE_FAMILY_URL` set at build time.

**To run it for real you need:**

1. **A host and a domain, with HTTPS.** Put the server behind a TLS-terminating proxy (Caddy, nginx, Fly.io, Render...). The app refuses plain `http://` except to localhost. `--public-url` must be the https address; it's used in email links and for the same-origin check.
2. **An email provider.** Set `BLINKWISE_SMTP_HOST`, `BLINKWISE_SMTP_PORT` (587), `BLINKWISE_SMTP_USER`, `BLINKWISE_SMTP_PASSWORD` and `BLINKWISE_MAIL_FROM`. Use a provider with SPF/DKIM set up for your domain (Postmark, Amazon SES, Mailgun...). Without these, emails are only printed to the log, which is fine for testing.
3. **Backups** of the SQLite file (`<data dir>/family.sqlite`, or `--db`).
4. **A privacy review for children's data.** This is not legal advice. In the US, COPPA applies to services that collect personal information from children under 13; here the parent creates the account and gives consent, and only aggregate, non-identifying numbers about the child are collected (the name is whatever the parent types, so a nickname works). In the EU/UK, GDPR (and the UK Children's Code) apply; you need a privacy notice, a lawful basis (parental consent), data-subject rights (export and deletion are built in), and a processor agreement with your host and email provider. Schools have their own rules (FERPA in the US). Have a lawyer review it before launching.

### Security design

* Sign-in links are single use, expire in 15 minutes, and are stored only as SHA-256 hashes. The same goes for sessions (30 days) and device tokens.
* Session cookies are `HttpOnly; SameSite=Lax` (`Secure` behind HTTPS). Every state-changing parent request also needs an `X-Blinkwise: 1` header and a matching `Origin`, so other sites can't forge them.
* Sign-in requests are rate limited (5 an hour per email and per IP) and always get the same answer, so the server never reveals whether an address has an account.
* Pairing codes are 8 characters from a 32-letter alphabet (about 10^12 combinations), expire in 24 hours, work once, and pairing is rate limited to 10 attempts an hour per IP.
* A parent can only see and change their own children. Device tokens can only write their own child's weeks.
* Strict CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, HSTS behind HTTPS.
* Old weeks are deleted after 26 weeks.

Tests: `tests/test_family.py` covers sign-in, link reuse and expiry, CSRF, rate limits, pairing, uploads, cross-account access, digests, stopping, removal, the PIN and schema validation.

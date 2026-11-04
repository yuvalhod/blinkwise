"""Family sharing: a child's Blinkwise shares weekly totals with a parent account.

  payload.py  what a child's computer sends (weekly totals only) and how it's validated
  client.py   pairing and the once-a-day upload, on the child's computer
  server.py   the reference server parents sign in to (magic-link email, no passwords)
  mail.py     email delivery (console outbox for development, SMTP for production)
"""

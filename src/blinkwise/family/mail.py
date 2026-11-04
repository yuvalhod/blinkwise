"""Email delivery for the family server.

  ConsoleMailer  keeps messages in memory and logs them (development, tests)
  SmtpMailer     any SMTP provider (Postmark, SES, Mailgun, Gmail with an app password...)
                 configured with environment variables:
                   BLINKWISE_SMTP_HOST, BLINKWISE_SMTP_PORT (587), BLINKWISE_SMTP_USER,
                   BLINKWISE_SMTP_PASSWORD, BLINKWISE_MAIL_FROM
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
import threading
from dataclasses import dataclass
from email.message import EmailMessage
from typing import List

log = logging.getLogger(__name__)


@dataclass
class Mail:
    to: str
    subject: str
    text: str


class ConsoleMailer:
    def __init__(self):
        self.outbox: List[Mail] = []
        self._lock = threading.Lock()

    def send(self, to: str, subject: str, text: str) -> None:
        with self._lock:
            self.outbox.append(Mail(to, subject, text))
        log.warning("[mail to %s] %s\n%s", to, subject, text)


class SmtpMailer:
    def __init__(self, host: str, port: int, user: str, password: str, sender: str):
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    @classmethod
    def from_env(cls) -> "SmtpMailer":
        env = os.environ
        return cls(env["BLINKWISE_SMTP_HOST"], int(env.get("BLINKWISE_SMTP_PORT", "587")),
                   env.get("BLINKWISE_SMTP_USER", ""), env.get("BLINKWISE_SMTP_PASSWORD", ""),
                   env["BLINKWISE_MAIL_FROM"])

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            if self.user:
                s.login(self.user, self.password)
            s.send_message(msg)


def from_env():
    return SmtpMailer.from_env() if os.environ.get("BLINKWISE_SMTP_HOST") else ConsoleMailer()

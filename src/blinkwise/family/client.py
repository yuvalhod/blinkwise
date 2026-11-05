"""The child's side of family sharing: pair once, then upload weekly totals once a day.

Nothing is sent until someone types a parent's pairing code. While sharing is on the
menu bar and dashboard say so, and "What's shared" shows the exact numbers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import ssl
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from . import payload as P

log = logging.getLogger(__name__)

DEFAULT_URL = os.environ.get("BLINKWISE_FAMILY_URL", "")
UPLOAD_EVERY_S = 6 * 3600


class FamilyError(Exception):
    pass


def check_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    u = urlparse(url)
    local = u.hostname in ("localhost", "127.0.0.1", "::1")
    if u.scheme != "https" and not (u.scheme == "http" and local):
        raise FamilyError("The family server address must start with https://")
    if not u.hostname or u.path not in ("", "/") or u.query or u.username:
        raise FamilyError("That doesn't look like a server address.")
    return url


def _ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _post(url: str, body: Dict[str, Any], token: Optional[str] = None, timeout: float = 15):
    headers = {"Content-Type": "application/json", "User-Agent": "Blinkwise"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
    ctx = _ssl() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:  # noqa: S310
            return r.status, json.loads(r.read(65536) or b"{}")
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read(65536) or b"{}")
        except ValueError:
            data = {}
        return e.code, data


def pair(url: str, code: str) -> Dict[str, str]:
    url = check_url(url)
    try:
        status, data = _post(url + "/api/device/pair", {"code": code})
    except OSError as e:
        raise FamilyError(f"Couldn't reach {urlparse(url).hostname}: {e}") from e
    if status != 200 or "token" not in data:
        raise FamilyError(data.get("error") or f"Pairing failed ({status}).")
    return {"url": url, "token": data["token"], "name": data.get("name", "")}


def upload(url: str, token: str, weeks: List[Dict[str, Any]]) -> int:
    """Returns the HTTP status. 401 means the parent removed this computer."""
    status, _ = _post(check_url(url) + "/api/device/summary", {"weeks": weeks}, token)
    return status


def unpair(url: str, token: str) -> None:
    try:
        _post(check_url(url) + "/api/device/unpair", {}, token)
    except (OSError, FamilyError):
        log.info("could not reach the family server to unpair; the link is removed here anyway")


def preview(history, settings, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Exactly what the next upload would send."""
    if history is None:
        return []
    return P.recent(history.daily(15), history.checkins(30), today or datetime.now().date(),
                    settings.family_share_checkin)


class Uploader:
    """Remembers the last upload time in a small file; upload at most every 6 hours."""

    def __init__(self, marker: Path):
        self.marker = marker

    def due(self, now: float) -> bool:
        try:
            return now - float(self.marker.read_text()) >= UPLOAD_EVERY_S
        except (OSError, ValueError):
            return True

    def mark(self, now: float) -> None:
        try:
            self.marker.parent.mkdir(parents=True, exist_ok=True)
            self.marker.write_text(str(now))
        except OSError:
            pass

    def run(self, history, settings, now: float, send=upload, force: bool = False) -> Optional[int]:
        if not settings.family_token or not settings.family_url or not (force or self.due(now)):
            return None
        weeks = preview(history, settings)
        self.mark(now)
        if not weeks:
            return None
        try:
            return send(settings.family_url, settings.family_token, weeks)
        except (OSError, FamilyError) as e:
            log.info("family upload failed: %s", e)
            return None


# ------------------------------------------------------------------ parent PIN
def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()


def check_pin(pin: str, stored: str) -> bool:
    if not stored:
        return True
    try:
        salt, digest = stored.split("$", 1)
        calc = hashlib.pbkdf2_hmac("sha256", str(pin).encode(), bytes.fromhex(salt), 200_000).hex()
    except ValueError:
        return False
    return hmac.compare_digest(calc, digest)


def valid_pin(pin: str) -> bool:
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 8

"""Once-a-day check for a newer release. Never downloads or installs anything.

The request is a plain anonymous GET of the public GitHub "latest release" page for
this project. It carries no identifiers, settings or usage data; GitHub sees an IP
address, as with any web request. Turn it off with ``check_updates = false``.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional, Tuple

from . import __version__

log = logging.getLogger(__name__)

REPO = "yuvalhod/blinkwise"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY_S = 24 * 3600
RETRY_AFTER_ERROR_S = 6 * 3600


def parse_version(v: str) -> Tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Pre-release suffixes are ignored, junk gives ()."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", v or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _ssl_context():
    """System trust store, or certifi's when available (the frozen Mac app has no other)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_latest(timeout: float = 10.0) -> Optional[dict]:
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                    "User-Agent": "Blinkwise"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:  # noqa: S310
        data = json.loads(r.read(200_000))
    if data.get("draft") or data.get("prerelease"):
        return None
    url = data.get("html_url") or RELEASES_URL
    if not str(url).startswith("https://github.com/"):
        url = RELEASES_URL
    return {"version": str(data.get("tag_name", "")).lstrip("v"), "url": url}


class UpdateChecker:
    """Remembers the last check in a small JSON file so restarts don't re-check."""

    def __init__(self, state_path: Path, fetch: Callable[[], Optional[dict]] = fetch_latest,
                 clock: Callable[[], float] = time.time):
        self.path = state_path
        self.fetch = fetch
        self.clock = clock
        self.state = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.state))
        except OSError:
            pass

    def due(self) -> bool:
        return self.clock() >= self.state.get("next_check", 0)

    def maybe_check(self) -> Optional[dict]:
        if self.due():
            now = self.clock()
            try:
                latest = self.fetch()
                self.state = {"checked": now, "next_check": now + CHECK_EVERY_S,
                              "latest": latest}
            except Exception as e:
                log.debug("update check failed: %s", e)
                self.state["next_check"] = now + RETRY_AFTER_ERROR_S
            self._save()
        return self.available()

    def available(self) -> Optional[dict]:
        latest = self.state.get("latest")
        if latest and is_newer(latest.get("version", "")):
            return latest
        return None

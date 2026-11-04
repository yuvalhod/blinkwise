"""A local-only web dashboard (stdlib http.server, no external assets).

Security model: binds to 127.0.0.1 only; rejects requests whose Host header
isn't localhost (blocks DNS-rebinding from web pages); state-changing POSTs
require a random per-run token that is only embedded in the page we serve.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, urlparse

from ..research import REFERENCES

log = logging.getLogger(__name__)

ALLOWED_ACTIONS = {"pause", "resume", "break_now", "skip_break", "wipe",
                   "calibrate", "calibrate_save", "calibrate_cancel", "calibrate_reset"}


def _static(name: str) -> str:
    return resources.files("blinkwise.ui").joinpath(f"static/{name}").read_text(encoding="utf-8")


def _index_html() -> str:
    return _static("index.html")


class DashboardServer:
    def __init__(self, port: int,
                 get_snapshot: Optional[Callable[[], Dict[str, Any]]] = None,
                 history=None,
                 on_action: Optional[Callable[[str], Dict[str, Any]]] = None,
                 get_settings: Optional[Callable[[], Any]] = None,
                 on_settings: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self.port = port
        self.get_snapshot = get_snapshot
        self.history = history
        self.on_action = on_action
        self.get_settings = get_settings
        self.on_settings = on_settings
        self.token = secrets.token_urlsafe(24)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> str:
        handler = self._make_handler()
        last_err: Optional[OSError] = None
        for port in range(self.port, self.port + 10):
            try:
                self._httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
                self.port = self._httpd.server_address[1]   # port 0: the OS picked one
                break
            except OSError as e:
                last_err = e
        if self._httpd is None:
            raise RuntimeError(f"Could not start dashboard: {last_err}")
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="dashboard",
                                        daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    # ------------------------------------------------------------------------
    def _make_handler(self):
        server = self
        page = _index_html()
        setup_page = _static("setup.html")

        class Handler(BaseHTTPRequestHandler):
            server_version = "Blinkwise"

            def log_message(self, fmt, *args):  # quiet
                log.debug("dashboard: " + fmt, *args)

            def _host_ok(self) -> bool:
                host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
                return host in ("127.0.0.1", "localhost", "::1")

            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                 "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                 "connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj: Any, code: int = 200) -> None:
                self._send(code, json.dumps(obj, default=_default).encode(), "application/json")

            def do_GET(self):  # noqa: N802
                if not self._host_ok():
                    return self._send(403, b"forbidden", "text/plain")
                u = urlparse(self.path)
                if u.path in ("/", "/index.html"):
                    html = page.replace("__BLINKWISE_TOKEN__", server.token)
                    return self._send(200, html.encode(), "text/html; charset=utf-8")
                if u.path == "/setup":
                    html = setup_page.replace("__BLINKWISE_TOKEN__", server.token)
                    return self._send(200, html.encode(), "text/html; charset=utf-8")
                if u.path == "/api/live":
                    snap = server.get_snapshot() if server.get_snapshot else None
                    return self._json({"running": snap is not None, **(snap or {})})
                if u.path == "/api/history":
                    q = parse_qs(u.query)
                    days = min(int(q.get("days", ["14"])[0]), 365)
                    hours = min(float(q.get("hours", ["8"])[0]), 48)
                    if server.history is None:
                        return self._json({"daily": [], "minutes": []})
                    return self._json({"daily": server.history.daily(days),
                                       "minutes": server.history.minutes(hours)})
                if u.path == "/api/insights":
                    q = parse_qs(u.query)
                    days = min(int(q.get("days", ["14"])[0]), 90)
                    if server.history is None:
                        return self._json({"hours_of_data": 0, "insights": []})
                    from ..core.analytics import report
                    return self._json(report(server.history.minute_rows(days)))
                if u.path == "/api/export":
                    data = server.history.export() if server.history is not None else {}
                    body = json.dumps(data, indent=1).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Disposition",
                                     'attachment; filename="blinkwise-data.json"')
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if u.path == "/api/weekly":
                    return self._json(server.weekly())
                if u.path == "/api/science":
                    return self._json([dataclasses.asdict(r) for r in REFERENCES.values()])
                if u.path == "/api/settings":
                    s = server.get_settings() if server.get_settings else None
                    return self._json(dataclasses.asdict(s) if s is not None else {})
                return self._send(404, b"not found", "text/plain")

            def do_POST(self):  # noqa: N802
                if not self._host_ok():
                    return self._send(403, b"forbidden", "text/plain")
                if not secrets.compare_digest(self.headers.get("X-Blinkwise-Token", ""), server.token):
                    return self._send(403, b"bad token", "text/plain")
                u = urlparse(self.path)
                n = min(int(self.headers.get("Content-Length") or 0), 4096)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._json({"error": "bad json"}, 400)
                if not isinstance(body, dict):
                    return self._json({"error": "expected an object"}, 400)
                if u.path == "/api/settings" and server.on_settings is not None:
                    try:
                        return self._json(dataclasses.asdict(server.on_settings(body)))
                    except (KeyError, ValueError, TypeError) as e:
                        return self._json({"error": str(e)}, 400)
                if u.path == "/api/checkin":
                    if server.history is None:
                        return self._json({"error": "history is off"}, 400)
                    try:
                        server.history.add_checkin(*(body.get(k) for k in ("dry", "tired", "blurry")))
                    except (TypeError, ValueError):
                        return self._json({"error": "answers must be 0-3"}, 400)
                    return self._json(server.weekly())
                if u.path != "/api/action" or server.on_action is None:
                    return self._send(404, b"not found", "text/plain")
                action = body.get("action")
                if action not in ALLOWED_ACTIONS:
                    return self._json({"error": "unknown action"}, 400)
                return self._json(server.on_action(action))

        return Handler

    def weekly(self) -> Dict[str, Any]:
        from ..core import weekly
        if self.history is None:
            return {"report": None, "checkin": None}
        days = self.history.daily(15)
        checkins = self.history.checkins()
        used = sum(1 for d in days if (d.get("screen_minutes") or 0) >= 10)
        return {"report": weekly.report(days, checkins),
                "checkin": {"due": weekly.checkin_due(checkins, used),
                            "questions": [{"key": k, "text": t} for k, t in weekly.QUESTIONS],
                            "answers": list(weekly.ANSWERS),
                            "advice": weekly.checkin_advice(checkins),
                            "last": checkins[-1] if checkins else None}}


def _default(o):
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    raise TypeError(type(o).__name__)

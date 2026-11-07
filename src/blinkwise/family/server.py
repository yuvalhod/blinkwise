"""Reference server for family sharing. Standard library + SQLite, no dependencies.

Parents
  * sign up / sign in with a magic link sent to their email (no passwords to leak);
  * add a child and get a pairing code to type into the child's Blinkwise;
  * see each child's weekly totals; optionally get them by email once a week.

Children's computers
  * pair once with the code and get a device token;
  * upload weekly totals (family/payload.py) at most a few times a day;
  * can stop sharing, which deletes their data here and tells the parent.

What it stores: parent email addresses, the child's display name the parent chose,
and weekly totals. No images, no per-minute data, no child email or account.

Security: single-use links that expire in 15 minutes; only SHA-256 hashes of links,
sessions and device tokens are stored; cookies are HttpOnly + SameSite=Lax (+ Secure
behind HTTPS); state-changing parent requests also need a same-origin header; sign-in
and pairing are rate limited; responses never reveal whether an email has an account.

Run it:  blinkwise family-server --public-url https://family.example.org
Deploying it for real needs HTTPS, an email provider, and a privacy review for
children's data (COPPA in the US, GDPR-K in the EU). See docs/FAMILY.md.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from . import payload as P

log = logging.getLogger(__name__)

LINK_TTL_S = 15 * 60
SESSION_TTL_S = 30 * 86400
PAIR_TTL_S = 24 * 3600
KEEP_WEEKS = 26
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # no 0/O, 1/I

SCHEMA = """
CREATE TABLE IF NOT EXISTS parents (
    id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, created INTEGER NOT NULL,
    digest INTEGER NOT NULL DEFAULT 1, last_digest TEXT
);
CREATE TABLE IF NOT EXISTS links (hash TEXT PRIMARY KEY, email TEXT NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, parent_id INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, name TEXT NOT NULL,
    code TEXT UNIQUE, code_expires INTEGER, device_hash TEXT UNIQUE,
    paired_at INTEGER, last_seen INTEGER, stopped_at INTEGER
);
CREATE TABLE IF NOT EXISTS weeks (
    child_id INTEGER NOT NULL, week TEXT NOT NULL, data TEXT NOT NULL, received INTEGER NOT NULL,
    PRIMARY KEY (child_id, week)
);
"""


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def norm_code(code: str) -> str:
    c = re.sub(r"[^A-Z0-9]", "", str(code).upper())
    return c[:4] + "-" + c[4:] if len(c) == 8 else ""


class RateLimit:
    def __init__(self, n: int, per_s: float):
        self.n, self.per_s = n, per_s
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def ok(self, key: str, now: Optional[float] = None) -> bool:
        now = now or time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.per_s:
                q.popleft()
            if len(q) >= self.n:
                return False
            q.append(now)
            return True


class FamilyStore:
    """All database access. Thread-safe."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        # Consent records (added after the first release; older databases get the columns).
        for table, col in (("parents", "terms_version TEXT"), ("parents", "terms_at INTEGER"),
                           ("children", "consent_at INTEGER")):
            try:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass                                # already there
        self._db.commit()
        self._lock = threading.Lock()

    def q(self, sql: str, args: tuple = ()) -> List[tuple]:
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
            self._db.commit()
            return rows

    # -- sign-in ---------------------------------------------------------------
    def new_link(self, email: str, now: float) -> str:
        token = secrets.token_urlsafe(32)
        self.q("DELETE FROM links WHERE expires < ?", (int(now),))
        self.q("INSERT INTO links VALUES (?,?,?)", (_h(token), email, int(now + LINK_TTL_S)))
        return token

    def use_link(self, token: str, now: float) -> Optional[str]:
        """Single use: the row is deleted whether or not it has expired."""
        with self._lock:
            row = self._db.execute("SELECT email, expires FROM links WHERE hash=?", (_h(token),)).fetchone()
            self._db.execute("DELETE FROM links WHERE hash=?", (_h(token),))
            self._db.commit()
        if row is None or row[1] < now:
            return None
        return row[0]

    def parent_for(self, email: str, now: float) -> int:
        """Sign-in links are only issued after the Terms/Privacy box is ticked, so a used
        link is a record of agreement: store which version and when."""
        from ..legal import TERMS_VERSION
        self.q("INSERT OR IGNORE INTO parents (email, created) VALUES (?,?)", (email, int(now)))
        self.q("UPDATE parents SET terms_version=?, terms_at=? WHERE email=? AND "
               "(terms_version IS NULL OR terms_version<>?)", (TERMS_VERSION, int(now), email, TERMS_VERSION))
        return self.q("SELECT id FROM parents WHERE email=?", (email,))[0][0]

    def new_session(self, parent_id: int, now: float) -> str:
        token = secrets.token_urlsafe(32)
        self.q("DELETE FROM sessions WHERE expires < ?", (int(now),))
        self.q("INSERT INTO sessions VALUES (?,?,?)", (_h(token), parent_id, int(now + SESSION_TTL_S)))
        return token

    def session_parent(self, token: str, now: float) -> Optional[int]:
        rows = self.q("SELECT parent_id FROM sessions WHERE hash=? AND expires>=?", (_h(token), int(now)))
        return rows[0][0] if rows else None

    def end_session(self, token: str) -> None:
        self.q("DELETE FROM sessions WHERE hash=?", (_h(token),))

    # -- children ----------------------------------------------------------------
    def add_child(self, parent_id: int, name: str, now: float) -> Dict[str, Any]:
        code = new_code()
        self.q("INSERT INTO children (parent_id, name, code, code_expires, consent_at) VALUES (?,?,?,?,?)",
               (parent_id, name, code, int(now + PAIR_TTL_S), int(now)))
        cid = self.q("SELECT id FROM children WHERE code=?", (code,))[0][0]
        return {"id": cid, "name": name, "code": code}

    def renew_code(self, parent_id: int, child_id: int, now: float) -> Optional[str]:
        code = new_code()
        n = self.q("SELECT 1 FROM children WHERE id=? AND parent_id=?", (child_id, parent_id))
        if not n:
            return None
        self.q("UPDATE children SET code=?, code_expires=? WHERE id=?", (code, int(now + PAIR_TTL_S), child_id))
        return code

    def remove_child(self, parent_id: int, child_id: int) -> bool:
        if not self.q("SELECT 1 FROM children WHERE id=? AND parent_id=?", (child_id, parent_id)):
            return False
        self.q("DELETE FROM weeks WHERE child_id=?", (child_id,))
        self.q("DELETE FROM children WHERE id=?", (child_id,))
        return True

    def children(self, parent_id: int, now: float) -> List[Dict[str, Any]]:
        out = []
        for cid, name, code, exp, dev, _paired, seen, stopped in self.q(
                "SELECT id, name, code, code_expires, device_hash, paired_at, last_seen, stopped_at "
                "FROM children WHERE parent_id=? ORDER BY id", (parent_id,)):
            weeks = [json.loads(d) for (d,) in self.q(
                "SELECT data FROM weeks WHERE child_id=? ORDER BY week DESC LIMIT 8", (cid,))]
            out.append({"id": cid, "name": name, "paired": dev is not None,
                        "code": code if (code and exp and exp >= now and dev is None) else None,
                        "last_seen": seen, "stopped_at": stopped, "weeks": weeks})
        return out

    # -- devices -------------------------------------------------------------------
    def pair(self, code: str, now: float) -> Optional[Tuple[str, str]]:
        rows = self.q("SELECT id, name FROM children WHERE code=? AND code_expires>=? AND device_hash IS NULL",
                      (code, int(now)))
        if not rows:
            return None
        cid, name = rows[0]
        token = secrets.token_urlsafe(32)
        self.q("UPDATE children SET device_hash=?, code=NULL, code_expires=NULL, paired_at=?, "
               "stopped_at=NULL WHERE id=?", (_h(token), int(now), cid))
        return token, name

    def device_child(self, token: str) -> Optional[int]:
        rows = self.q("SELECT id FROM children WHERE device_hash=?", (_h(token),))
        return rows[0][0] if rows else None

    def store_week(self, child_id: int, data: Dict[str, Any], now: float) -> None:
        self.q("INSERT OR REPLACE INTO weeks VALUES (?,?,?,?)",
               (child_id, data["week_start"], json.dumps(data), int(now)))
        self.q("UPDATE children SET last_seen=? WHERE id=?", (int(now), child_id))
        cutoff = (date.fromisoformat(data["week_start"]) - timedelta(weeks=KEEP_WEEKS)).isoformat()
        self.q("DELETE FROM weeks WHERE child_id=? AND week<?", (child_id, cutoff))

    def unpair(self, child_id: int, now: float) -> None:
        """The child stopped sharing: their data is deleted; the parent sees that it stopped."""
        self.q("DELETE FROM weeks WHERE child_id=?", (child_id,))
        self.q("UPDATE children SET device_hash=NULL, stopped_at=? WHERE id=?", (int(now), child_id))

    # -- digests -------------------------------------------------------------------
    def digest_targets(self) -> List[Tuple[int, str, Optional[str]]]:
        return self.q("SELECT id, email, last_digest FROM parents WHERE digest=1")

    def set_digest(self, parent_id: int, on: bool) -> None:
        self.q("UPDATE parents SET digest=? WHERE id=?", (int(on), parent_id))

    def parent(self, parent_id: int) -> Dict[str, Any]:
        email, digest = self.q("SELECT email, digest FROM parents WHERE id=?", (parent_id,))[0]
        return {"email": email, "digest": bool(digest)}

    def delete_parent(self, parent_id: int) -> None:
        for (cid,) in self.q("SELECT id FROM children WHERE parent_id=?", (parent_id,)):
            self.q("DELETE FROM weeks WHERE child_id=?", (cid,))
        self.q("DELETE FROM children WHERE parent_id=?", (parent_id,))
        self.q("DELETE FROM sessions WHERE parent_id=?", (parent_id,))
        self.q("DELETE FROM parents WHERE id=?", (parent_id,))


# ---------------------------------------------------------------------------- digest
def digest_text(children: List[Dict[str, Any]], week: str, base_url: str) -> Optional[str]:
    lines = []
    for c in children:
        w = next((x for x in c["weeks"] if x.get("week_start") == week), None)
        if w is None:
            if c["paired"]:
                lines.append(f"{c['name']}: no data this week (Blinkwise wasn't running).")
            elif c["stopped_at"]:
                lines.append(f"{c['name']}: stopped sharing.")
            continue
        lines.append(f"{c['name']} - week of {week}")
        lines += [f"  {label}: {value}" for label, value in P.describe(w) if label != "Week starting"]
        lines.append("")
    if not lines:
        return None
    return ("\n".join(lines) + f"\nSee more or change email settings: {base_url}\n\n"
            "Blinkwise is a habit tool, not a medical device. If your child often has sore, dry "
            "or tired eyes, or blurry vision, see an eye-care professional.")


def send_digests(store: FamilyStore, mailer, base_url: str, today: Optional[date] = None) -> int:
    """Email last week's totals to parents who want them. Safe to call often (once per week)."""
    today = today or datetime.now().date()
    week = P.week_start(today - timedelta(days=7)).isoformat()
    sent = 0
    for pid, email, last in store.digest_targets():
        if last == week:
            continue
        text = digest_text(store.children(pid, time.time()), week, base_url)
        store.q("UPDATE parents SET last_digest=? WHERE id=?", (week, pid))
        if text:
            mailer.send(email, f"Blinkwise: your family's eye habits, week of {week}", text)
            sent += 1
    return sent


# ------------------------------------------------------------------------------ http
class FamilyServer:
    def __init__(self, db_path: Path, mailer, public_url: str = "", host: str = "127.0.0.1",
                 port: int = 8790, digest_hour: int = 8):
        self.store = FamilyStore(db_path)
        self.mailer = mailer
        self.host, self.port = host, port
        self.public_url = public_url.rstrip("/")
        self.digest_hour = digest_hour
        self.signin_limit = RateLimit(5, 3600)        # per email and per IP
        self.pair_limit = RateLimit(10, 3600)         # per IP (codes are 32^8)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._stop = threading.Event()

    @property
    def base_url(self) -> str:
        return self.public_url or f"http://{self.host}:{self.port}"

    @property
    def secure(self) -> bool:
        return self.base_url.startswith("https://")

    def start(self) -> str:
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._handler())
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, name="family-http", daemon=True).start()
        threading.Thread(target=self._digest_loop, name="family-digest", daemon=True).start()
        return self.base_url + "/"

    def stop(self) -> None:
        self._stop.set()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()

    def _digest_loop(self) -> None:
        while not self._stop.wait(600):
            now = datetime.now()
            if now.weekday() == 0 and now.hour >= self.digest_hour:   # Monday morning
                try:
                    send_digests(self.store, self.mailer, self.base_url)
                except Exception:
                    log.exception("digest failed")

    def _handler(self):
        server = self

        class H(BaseHTTPRequestHandler):
            server_version = "BlinkwiseFamily"
            sys_version = ""

            def log_message(self, fmt, *args):
                log.debug("family %s - %s", self.address_string(), fmt % args)

            # -- helpers ---------------------------------------------------------
            def _send(self, code: int, body: bytes, ctype: str, headers: Dict[str, str] = None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                 "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; "
                                 "form-action 'self'")
                if server.secure:
                    self.send_header("Strict-Transport-Security", "max-age=31536000")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj: Any, code: int = 200, headers=None):
                self._send(code, json.dumps(obj).encode(), "application/json", headers)

            def _body(self) -> Dict[str, Any]:
                n = min(int(self.headers.get("Content-Length") or 0), 16384)
                raw = self.rfile.read(n) if n else b""
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("application/x-www-form-urlencoded"):
                    return {k: v[0] for k, v in parse_qs(raw.decode(errors="replace")).items()}
                try:
                    data = json.loads(raw or b"{}")
                except ValueError:
                    return {}
                return data if isinstance(data, dict) else {}

            def _ip(self) -> str:
                return self.client_address[0]

            def _session(self) -> Optional[str]:
                c = SimpleCookie(self.headers.get("Cookie", ""))
                return c["bw_session"].value if "bw_session" in c else None

            def _parent(self) -> Optional[int]:
                tok = self._session()
                return server.store.session_parent(tok, time.time()) if tok else None

            def _same_origin(self) -> bool:
                """CSRF: parent API calls come from our own page's fetch()."""
                if self.headers.get("X-Blinkwise") != "1":
                    return False
                origin = self.headers.get("Origin")
                return origin is None or origin.rstrip("/") == server.base_url

            def _cookie(self, value: str, max_age: int) -> str:
                return (f"bw_session={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
                        + ("; Secure" if server.secure else ""))

            def _bearer(self) -> Optional[int]:
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    return None
                return server.store.device_child(auth[7:].strip())

            # -- routes -------------------------------------------------------------
            def do_GET(self):  # noqa: N802
                u = urlparse(self.path)
                if u.path == "/":
                    pid = self._parent()
                    page = PARENT_PAGE if pid else SIGNIN_PAGE
                    return self._send(200, page.encode(), "text/html; charset=utf-8")
                if u.path == "/auth":
                    token = parse_qs(u.query).get("t", [""])[0]
                    email = server.store.use_link(token, time.time()) if token else None
                    if email is None:
                        return self._send(400, _msg_page("This sign-in link has expired or was "
                                                         "already used. Request a new one.").encode(),
                                          "text/html; charset=utf-8")
                    pid = server.store.parent_for(email, time.time())
                    sess = server.store.new_session(pid, time.time())
                    return self._send(303, b"", "text/plain",
                                      {"Location": "/", "Set-Cookie": self._cookie(sess, SESSION_TTL_S)})
                if u.path == "/api/me":
                    pid = self._parent()
                    if pid is None:
                        return self._json({"error": "signed out"}, 401)
                    return self._json({**server.store.parent(pid),
                                       "children": server.store.children(pid, time.time()),
                                       "labels": {k: v[3] for k, v in P.FIELDS.items()}})
                from ..ui.dashboard import asset
                a = asset(u.path)
                if a is not None:
                    return self._send(200, a[0], a[1])
                if u.path in ("/privacy", "/terms"):
                    from .. import legal
                    return self._send(200, legal.page(u.path[1:]).encode(), "text/html; charset=utf-8")
                if u.path == "/healthz":
                    return self._json({"ok": True})
                return self._send(404, b"not found", "text/plain")

            def do_POST(self):  # noqa: N802
                u = urlparse(self.path)
                now = time.time()
                body = self._body()
                # ---- sign in (public) ----
                if u.path == "/auth/start":
                    email = str(body.get("email", "")).strip().lower()
                    if not EMAIL_RE.match(email):
                        return self._json({"error": "Enter a valid email address."}, 400)
                    if body.get("agree") is not True:
                        return self._json({"error": "Please confirm you're an adult and agree to "
                                                     "the Terms and Privacy Policy."}, 400)
                    if server.signin_limit.ok("ip:" + self._ip()) and server.signin_limit.ok("em:" + email):
                        token = server.store.new_link(email, now)
                        server.mailer.send(email, "Your Blinkwise sign-in link",
                                           f"Sign in to Blinkwise Family:\n\n{server.base_url}/auth?t={token}\n\n"
                                           "The link works once and expires in 15 minutes. If you didn't "
                                           "ask for it, ignore this email.")
                    # Same answer either way: no account enumeration, no rate-limit oracle.
                    return self._json({"ok": True})
                # ---- device API (bearer token) ----
                if u.path == "/api/device/pair":
                    if not server.pair_limit.ok(self._ip()):
                        return self._json({"error": "Too many attempts. Try again later."}, 429)
                    res = server.store.pair(norm_code(body.get("code", "")), now)
                    if res is None:
                        return self._json({"error": "That code isn't valid or has expired."}, 400)
                    return self._json({"token": res[0], "name": res[1]})
                if u.path in ("/api/device/summary", "/api/device/unpair"):
                    cid = self._bearer()
                    if cid is None:
                        return self._json({"error": "not paired"}, 401)
                    if u.path.endswith("unpair"):
                        server.store.unpair(cid, now)
                        return self._json({"ok": True})
                    weeks = body.get("weeks")
                    if not isinstance(weeks, list) or not 1 <= len(weeks) <= 2:
                        return self._json({"error": "expected 1-2 weeks"}, 400)
                    try:
                        clean = [P.validate(w) for w in weeks]
                    except ValueError as e:
                        return self._json({"error": str(e)}, 400)
                    for w in clean:
                        server.store.store_week(cid, w, now)
                    return self._json({"ok": True})
                # ---- parent API (session cookie + same-origin header) ----
                if not self._same_origin():
                    return self._json({"error": "forbidden"}, 403)
                pid = self._parent()
                if pid is None:
                    return self._json({"error": "signed out"}, 401)
                if u.path == "/auth/signout":
                    server.store.end_session(self._session() or "")
                    return self._json({"ok": True}, headers={"Set-Cookie": self._cookie("", 0)})
                if u.path == "/api/children":
                    name = re.sub(r"\s+", " ", str(body.get("name", ""))).strip()[:40]
                    if not name:
                        return self._json({"error": "Give your child a name or nickname."}, 400)
                    if body.get("guardian") is not True:
                        return self._json({"error": "Please confirm you're this child's parent or "
                                                     "legal guardian and consent to sharing."}, 400)
                    if len(server.store.children(pid, now)) >= 10:
                        return self._json({"error": "Up to 10 children per account."}, 400)
                    return self._json(server.store.add_child(pid, name, now))
                m = re.fullmatch(r"/api/children/(\d+)/(code|remove)", u.path)
                if m:
                    cid = int(m.group(1))
                    if m.group(2) == "code":
                        code = server.store.renew_code(pid, cid, now)
                        return self._json({"code": code} if code else {"error": "not found"},
                                          200 if code else 404)
                    ok = server.store.remove_child(pid, cid)
                    return self._json({"ok": ok}, 200 if ok else 404)
                if u.path == "/api/digest":
                    server.store.set_digest(pid, bool(body.get("on")))
                    return self._json({"ok": True})
                if u.path == "/api/account/delete":
                    server.store.delete_parent(pid)
                    return self._json({"ok": True}, headers={"Set-Cookie": self._cookie("", 0)})
                return self._send(404, b"not found", "text/plain")

        return H


def _msg_page(text: str) -> str:
    return SIGNIN_PAGE.replace("<!--MSG-->", f'<p class="msg">{html.escape(text)}</p>')


_STYLE = """
.wrap{max-width:760px;margin:0 auto;padding:24px 20px 64px}
.top{display:flex;align-items:center;gap:12px;padding-bottom:16px;border-bottom:1px solid var(--ink);margin-bottom:28px}
.top .fam{font:italic 400 15px var(--display);color:var(--muted)}
.sheet{background:var(--sheet);border:1px solid var(--rule);border-top:2px solid var(--ink);padding:22px 24px;margin-bottom:18px}
h1{font-size:44px;line-height:1.05;margin:0 0 10px;letter-spacing:-.02em}
h2{font-size:28px}
.lead{font:italic 400 19px/1.45 var(--display);color:var(--muted);margin:0 0 22px}
.small{font-size:13.5px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.row input{flex:1;min-width:200px}
.msg{padding:12px 14px;border-left:3px solid var(--good);background:var(--good-soft)}
.code{font:400 40px/1.1 var(--display);letter-spacing:.06em;display:inline-block;padding:8px 0;border-bottom:2px solid var(--hot)}
.grid{display:grid;grid-template-columns:1fr auto auto;gap:0;font-size:14.5px;margin-top:14px;align-items:baseline}
.grid>*{padding:9px 0;border-top:1px solid var(--rule2)}
.grid .h{font:700 11px/1 var(--text);letter-spacing:.12em;text-transform:uppercase;color:var(--faint);border-top:0}
.grid .v{text-align:right;font:400 20px/1 var(--display);padding-left:18px}
.grid .p{text-align:right;color:var(--faint);padding-left:18px}
.head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}.head .sp{flex:1}
.chip.off{color:var(--faint)}
.chip.on{color:var(--good)}
.link{color:var(--hot);font-size:13.5px}
label.check{display:flex;gap:10px;align-items:flex-start;font-size:14px;line-height:1.45}
label.check input{margin-top:3px;flex:none;accent-color:var(--ink)}
footer.legal{margin-top:28px;padding-top:14px;border-top:1px solid var(--rule);font-size:13px;color:var(--muted);display:flex;gap:16px;flex-wrap:wrap}
"""

_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Blinkwise Family</title>
<link rel="stylesheet" href="/theme.css"><style>""" + _STYLE + """</style></head><body><div class="wrap">
<header class="top"><span class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M4 21c8-9 24-9 32 0" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M4 21c8 8 24 8 32 0" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><circle cx="20" cy="21" r="5.2" fill="var(--hot)"/><path d="M9 14.5 7 11M14.5 11.5 13.5 8M20 10.5V7M25.5 11.5 26.5 8M31 14.5 33 11" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>Blinkwise</span><span class="fam">Family</span><span style="flex:1"></span><!--NAV--></header>"""


SIGNIN_PAGE = _HEAD + """
<h1>Your family's eye habits, once a week.</h1>
<p class="lead">Screen time, blink rate and breaks for each child, from Blinkwise on their computer. Sign in with your email; there's no password.</p>
<div class="sheet">
<!--MSG-->
<form id="f"><div class="row"><input type="email" id="email" required placeholder="you@example.com" autocomplete="email" aria-label="Email"><button class="primary">Email me a link</button></div>
<label class="check" style="margin-top:14px"><input type="checkbox" id="agree" required style="width:auto"> I'm 18 or older and agree to the <a href="/terms" target="_blank" rel="noopener">Terms of Use</a> and <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.</label></form>
<p id="sent" class="msg" hidden>Check your inbox for a sign-in link. It works once, for 15 minutes.</p>
<p id="err" class="small" style="color:var(--hot)" hidden></p>
</div>
<p class="small muted">Only weekly totals are shared, never video, images or minute-by-minute data. Your child sees exactly what's shared, and when.</p>
<footer class="legal"><span>Not a medical device</span><a href="/privacy">Privacy</a><a href="/terms">Terms</a></footer>
</div><script>
document.getElementById("f").onsubmit = async e => {
  e.preventDefault();
  const r = await fetch("/auth/start", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({email: document.getElementById("email").value, agree: document.getElementById("agree").checked})});
  const d = await r.json().catch(() => ({}));
  document.getElementById("err").hidden = r.ok; document.getElementById("err").textContent = d.error || "";
  document.getElementById("sent").hidden = !r.ok; if (r.ok) document.getElementById("f").hidden = true;
};
</script></body></html>"""

PARENT_PAGE = _HEAD.replace("<!--NAV-->", '<button id="out" class="ghost">Sign out</button>') + """
<div id="kids"></div>
<div class="sheet"><h2>Add a child</h2>
<p class="muted small">You'll get a code to type into Blinkwise on their computer (Settings, Family).</p>
<form id="add"><div class="row"><input id="name" maxlength="40" placeholder="Name or nickname" aria-label="Child's name"><button class="primary">Get a code</button></div>
<label class="check" style="margin-top:12px"><input type="checkbox" id="guardian" required style="width:auto"> I'm this child's parent or legal guardian. I consent to their computer sharing the weekly totals described in the <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>, and I'll tell them it's on.</label></form></div>
<div class="sheet"><div class="head"><h2>Monday email</h2><span class="sp"></span><label class="check"><input type="checkbox" id="digest" style="width:auto"> Send me the weekly totals</label></div>
<p class="muted small" id="me"></p>
<p class="small"><a href="#" id="del" class="link">Delete my account and all data</a></p></div>
<footer class="legal"><span>Not a medical device</span><a href="/privacy">Privacy</a><a href="/terms">Terms</a></footer>
</div><script>
const H = {"Content-Type":"application/json","X-Blinkwise":"1"};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const post = (u, b) => fetch(u, {method:"POST", headers:H, body: JSON.stringify(b || {})}).then(r => r.json());
const SHOW = ["screen_per_day","phone_per_day","blink_rate","full_blinks","breaks_pct","posture_per_day","distance_cm","checkin_total"];
function ago(ts){ if (!ts) return "never"; const d = Math.floor((Date.now()/1000 - ts)/86400); return d < 1 ? "today" : d === 1 ? "yesterday" : d + " days ago"; }
async function load(){
  const r = await fetch("/api/me"); if (r.status === 401) { location.reload(); return; }
  const me = await r.json();
  document.getElementById("digest").checked = me.digest;
  document.getElementById("me").textContent = "Signed in as " + me.email;
  document.getElementById("kids").innerHTML = me.children.map(c => {
    const [w, p] = [c.weeks[0], c.weeks[1]];
    let body;
    if (!c.paired && c.code) body = `<p class="muted small">On ${esc(c.name)}'s computer, open Blinkwise, Settings, Family, and enter:</p><span class="code">${esc(c.code)}</span><p class="muted small">Valid for 24 hours.</p>`;
    else if (!c.paired) body = `<p class="muted small">${c.stopped_at ? "Sharing was stopped on " + esc(c.name) + "'s computer, and their data here was deleted." : "Not connected."}</p><button data-code="${c.id}">New code</button>`;
    else if (!w) body = `<p class="muted small">Connected. The first weekly totals arrive within a day.</p>`;
    else body = `<div class="grid"><span class="h">Week of ${esc(w.week_start)} · ${w.days_active} day${w.days_active === 1 ? "" : "s"}</span><span class="h" style="text-align:right">This week</span><span class="h" style="text-align:right">${p ? "Before" : ""}</span>` +
      SHOW.filter(k => k in w).map(k => `<span class="muted">${esc(me.labels[k])}</span><span class="v">${esc(w[k])}</span><span class="p">${p && k in p ? esc(p[k]) : ""}</span>`).join("") + `</div>`;
    return `<div class="sheet"><div class="head"><h2>${esc(c.name)}</h2><span class="chip ${c.paired ? "on" : "off"}">${c.paired ? "Sharing" : "Not connected"}</span><span class="sp"></span><span class="faint small">${c.paired ? "Updated " + ago(c.last_seen) : ""}</span></div>${body}
      <p class="small" style="margin:14px 0 0"><a href="#" class="link" data-rm="${c.id}">Remove</a></p></div>`;
  }).join("");
  document.querySelectorAll("[data-code]").forEach(b => b.onclick = async () => { await post(`/api/children/${b.dataset.code}/code`); load(); });
  document.querySelectorAll("[data-rm]").forEach(a => a.onclick = async e => { e.preventDefault(); if (confirm("Remove this child and delete their data?")) { await post(`/api/children/${a.dataset.rm}/remove`); load(); } });
}
document.getElementById("add").onsubmit = async e => { e.preventDefault(); const d = await post("/api/children", {name: document.getElementById("name").value, guardian: document.getElementById("guardian").checked}); if (d.error) alert(d.error); document.getElementById("name").value = ""; load(); };
document.getElementById("digest").onchange = e => post("/api/digest", {on: e.target.checked});
document.getElementById("out").onclick = async () => { await post("/auth/signout"); location.href = "/"; };
document.getElementById("del").onclick = async e => { e.preventDefault(); if (confirm("Delete your account, your children's links and all their data?")) { await post("/api/account/delete"); location.href = "/"; } };
load();
</script></body></html>"""

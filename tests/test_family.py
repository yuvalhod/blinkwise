"""Family sharing: payload, parent server (sign-in, pairing, uploads, digests), client, kids mode."""

import http.client
import json
import time
from datetime import date, timedelta
from urllib.parse import urlparse

import pytest

from blinkwise.family import client
from blinkwise.family import payload as P
from blinkwise.family.mail import ConsoleMailer
from blinkwise.family.server import LINK_TTL_S, FamilyServer, norm_code, send_digests

MONDAY = date(2026, 11, 2)


def day(d, **kw):
    base = dict(day=d.isoformat(), screen_minutes=200, device_minutes=30, observed_minutes=200,
                blinks=200 * 10, incomplete_ratio=0.25, distance_cm=55, breaks_taken=6,
                breaks_missed=2, posture_minutes=12)
    base.update(kw)
    return base


# ------------------------------------------------------------------- payload
def test_payload_is_weekly_totals_only():
    days = [day(MONDAY + timedelta(days=i)) for i in range(3)]
    p = P.build(days, [], MONDAY)
    assert p == {"v": 1, "week_start": "2026-11-02", "days_active": 3, "screen_per_day": 200,
                 "phone_per_day": 30, "blink_rate": 10.0, "full_blinks": 75, "breaks_pct": 75,
                 "breaks_taken": 18, "distance_cm": 55, "posture_per_day": 12}
    assert P.validate(p) == p
    assert P.build([], [], MONDAY) is None


def test_checkin_score_only_when_the_child_chooses():
    ts = time.mktime((MONDAY + timedelta(days=2)).timetuple()) + 3600
    ck = [{"ts": ts, "dry": 1, "tired": 2, "blurry": 0}]
    days = [day(MONDAY)]
    assert "checkin_total" not in P.build(days, ck, MONDAY)
    assert P.build(days, ck, MONDAY, share_checkin=True)["checkin_total"] == 3


@pytest.mark.parametrize("bad", [
    {"v": 1, "week_start": "2026-11-03"},                                 # not a Monday
    {"v": 1, "week_start": "2026-11-02", "screen_per_day": 5000},          # out of range
    {"v": 1, "week_start": "2026-11-02", "blink_rate": True},              # bool is not a number
    {"v": 1, "week_start": "2026-11-02", "email": "kid@example.com"},      # unknown field
    {"v": 2, "week_start": "2026-11-02"},
    {"v": 1},
    "junk",
])
def test_server_rejects_anything_else(bad):
    with pytest.raises(ValueError):
        P.validate(bad)


def test_pairing_codes_and_urls():
    assert norm_code("abcd ef23") == "ABCD-EF23" and norm_code("abc") == ""
    assert client.check_url("https://family.example.org/") == "https://family.example.org"
    assert client.check_url("http://127.0.0.1:8790") == "http://127.0.0.1:8790"
    for bad in ("http://family.example.org", "ftp://x.org", "https://x.org/path", "https://u@x.org", ""):
        with pytest.raises(client.FamilyError):
            client.check_url(bad)


def test_pin_hashing():
    h = client.hash_pin("2468")
    assert "2468" not in h and client.check_pin("2468", h) and not client.check_pin("1357", h)
    assert client.check_pin("anything", "")          # no PIN set
    assert not client.check_pin("2468", "garbage")
    assert client.valid_pin("1234") and not client.valid_pin("12") and not client.valid_pin("abcd")


# -------------------------------------------------------------------- server
class Web:
    """Minimal browser: keeps the session cookie, sends the same-origin header."""

    def __init__(self, url):
        u = urlparse(url)
        self.host, self.port, self.base = u.hostname, u.port, url.rstrip("/")
        self.cookie = None

    def req(self, method, path, body=None, headers=None, same_origin=True):
        c = http.client.HTTPConnection(self.host, self.port, timeout=10)
        h = {"Content-Type": "application/json"}
        if same_origin:
            h["X-Blinkwise"] = "1"
            h["Origin"] = self.base
        if self.cookie:
            h["Cookie"] = self.cookie
        h.update(headers or {})
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0]
        try:
            return r.status, json.loads(data), r
        except ValueError:
            return r.status, data, r


@pytest.fixture
def fam(tmp_path):
    srv = FamilyServer(tmp_path / "family.sqlite", ConsoleMailer(), port=0)
    url = srv.start()
    yield srv, url
    srv.stop()


def sign_in(srv, web, email="parent@example.com"):
    n = len(srv.mailer.outbox)
    assert web.req("POST", "/auth/start", {"email": email}, same_origin=False)[0] == 200
    mail = srv.mailer.outbox[n]
    link = mail.text.split("\n")[2]
    status, _, r = web.req("GET", urlparse(link).path + "?" + urlparse(link).query)
    cookie = r.getheader("Set-Cookie")
    assert status == 303 and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    return link


def test_magic_link_sign_in(fam):
    srv, url = fam
    web = Web(url)
    assert web.req("POST", "/auth/start", {"email": "nope"})[0] == 400
    assert web.req("GET", "/api/me")[0] == 401
    link = sign_in(srv, web)
    status, me, _ = web.req("GET", "/api/me")
    assert status == 200 and me["email"] == "parent@example.com" and me["children"] == []
    # Single use.
    again = Web(url)
    assert again.req("GET", urlparse(link).path + "?" + urlparse(link).query)[0] == 400
    # Expired links don't work.
    tok = srv.store.new_link("x@example.com", time.time())
    assert srv.store.use_link(tok, time.time() + LINK_TTL_S + 1) is None
    # Only hashes are stored.
    assert not srv.store.q("SELECT 1 FROM links WHERE hash=?", (tok,))


def test_sign_in_is_rate_limited_without_revealing_it(fam):
    srv, url = fam
    web = Web(url)
    for _ in range(8):
        assert web.req("POST", "/auth/start", {"email": "a@example.com"}, same_origin=False)[0] == 200
    assert len(srv.mailer.outbox) == 5


def test_csrf_protection(fam):
    srv, url = fam
    web = Web(url)
    sign_in(srv, web)
    assert web.req("POST", "/api/children", {"name": "Sam"}, same_origin=False)[0] == 403
    assert web.req("POST", "/api/children", {"name": "Sam"},
                   headers={"Origin": "https://evil.example"})[0] == 403
    assert web.req("POST", "/api/children", {"name": "Sam"})[0] == 200


def test_full_family_flow(fam):
    srv, url = fam
    parent = Web(url)
    sign_in(srv, parent)
    status, kid, _ = parent.req("POST", "/api/children", {"name": "Sam"})
    assert status == 200 and len(kid["code"]) == 9
    # The child's computer pairs with the code (any case / spacing).
    res = client.pair(url, kid["code"].lower().replace("-", " "))
    assert res["name"] == "Sam"
    with pytest.raises(client.FamilyError):
        client.pair(url, kid["code"])                   # codes work once
    # Uploads.
    weeks = [P.build([day(MONDAY + timedelta(days=i)) for i in range(5)], [], MONDAY)]
    assert client.upload(url, res["token"], weeks) == 200
    assert client.upload(url, "wrong-token", weeks) == 401
    assert client.upload(url, res["token"], [{**weeks[0], "secret": 1}]) == 400
    _, me, _ = parent.req("GET", "/api/me")
    sam = me["children"][0]
    assert sam["paired"] and sam["weeks"][0]["screen_per_day"] == 200 and sam["code"] is None
    # Weekly email (sent once).
    assert send_digests(srv.store, srv.mailer, url, today=MONDAY + timedelta(days=7)) == 1
    mail = srv.mailer.outbox[-1]
    assert "Sam - week of 2026-11-02" in mail.text and "Screen time a day (min): 200" in mail.text
    assert send_digests(srv.store, srv.mailer, url, today=MONDAY + timedelta(days=8)) == 0
    # Another parent can't touch Sam.
    other = Web(url)
    sign_in(srv, other, "other@example.com")
    assert other.req("POST", f"/api/children/{sam['id']}/remove")[0] == 404
    assert other.req("GET", "/api/me")[1]["children"] == []
    # The child stops sharing: data deleted, parent told.
    client.unpair(url, res["token"])
    sam = parent.req("GET", "/api/me")[1]["children"][0]
    assert not sam["paired"] and sam["stopped_at"] and sam["weeks"] == []
    assert client.upload(url, res["token"], weeks) == 401
    # Digest opt-out and account deletion.
    assert parent.req("POST", "/api/digest", {"on": False})[0] == 200
    assert parent.req("POST", "/api/account/delete")[0] == 200
    assert parent.req("GET", "/api/me")[0] == 401
    assert srv.store.q("SELECT COUNT(*) FROM children")[0][0] == 0


def test_parent_removing_a_child_disconnects_the_device(fam):
    srv, url = fam
    parent = Web(url)
    sign_in(srv, parent)
    kid = parent.req("POST", "/api/children", {"name": "Ana"})[1]
    tok = client.pair(url, kid["code"])["token"]
    assert parent.req("POST", f"/api/children/{kid['id']}/remove")[0] == 200
    assert client.upload(url, tok, [{"v": 1, "week_start": "2026-11-02"}]) == 401


def test_pairing_is_rate_limited(fam):
    srv, url = fam
    for _ in range(10):
        with pytest.raises(client.FamilyError, match="isn't valid"):
            client.pair(url, "AAAA-AAAA")
    with pytest.raises(client.FamilyError, match="Too many"):
        client.pair(url, "AAAA-AAAA")


# ----------------------------------------------------------- the child's app
def test_app_family_control_end_to_end(fam, tmp_path):
    from blinkwise.app import App
    from blinkwise.config import Settings
    from blinkwise.core.events import MinuteSummary

    srv, url = fam
    parent = Web(url)
    sign_in(srv, parent)
    kid = parent.req("POST", "/api/children", {"name": "Sam"})[1]

    app = App(Settings(profile="young"), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    now = time.time()
    for m in range(30):
        app.history.record(MinuteSummary(t=0, observed_s=60, blinks=11, judged=0, incomplete=0,
                                         long=0, max_stare_s=4, distance_cm=52, zones=1,
                                         screen_s=60), now - 3600 + m * 60)
    fc = app.family
    before = fc.get()
    assert not before["paired"] and before["kids"] and before["preview"]    # shown before sharing
    with pytest.raises(ValueError, match="isn't valid"):
        fc.post({"op": "pair", "url": url, "code": "ZZZZ-ZZZZ"})
    sent = []
    fc.post({"op": "pair", "url": url, "code": kid["code"]})
    fc.maybe_upload(force=True, send=lambda u, t, w: sent.append(w) or client.upload(u, t, w))
    assert sent and sent[0][-1]["screen_per_day"] == 30
    assert parent.req("GET", "/api/me")[1]["children"][0]["weeks"]
    app._publish()
    assert app.snapshot()["family_sharing"]
    assert Settings.load().public_dict()["family_token"] is True            # never shown to UIs

    # Parent PIN locks settings and stopping, but not the child's own check-in choice.
    with pytest.raises(ValueError):
        fc.post({"op": "set_pin", "pin": "12"})
    fc.post({"op": "set_pin", "pin": "2468"})
    with pytest.raises(PermissionError):
        app._on_settings({"blink_cue": "off"})
    app._on_settings({"blink_cue": "off", "pin": "2468"})
    with pytest.raises(PermissionError):
        fc.post({"op": "stop"})
    fc.post({"op": "share_checkin", "on": True})
    with pytest.raises(PermissionError):
        fc.post({"op": "set_pin", "old": "0000", "pin": ""})

    # The parent removes this computer -> the next upload notices and says so.
    parent.req("POST", f"/api/children/{parent.req('GET', '/api/me')[1]['children'][0]['id']}/remove")
    fc.maybe_upload(force=True)
    st = fc.get()
    assert not st["paired"] and st["removed"] and not app.s.family_token
    app.history.close()


def test_stop_sharing_with_pin(fam, tmp_path):
    from blinkwise.app import App
    from blinkwise.config import Settings

    srv, url = fam
    parent = Web(url)
    sign_in(srv, parent)
    kid = parent.req("POST", "/api/children", {"name": "Lee"})[1]
    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    app.family.post({"op": "pair", "url": url, "code": kid["code"]})
    app.family.post({"op": "set_pin", "pin": "1357"})
    app.family.post({"op": "stop", "pin": "1357"})
    assert not app.s.family_token
    for _ in range(50):
        if parent.req("GET", "/api/me")[1]["children"][0]["stopped_at"]:
            break
        time.sleep(0.05)
    assert parent.req("GET", "/api/me")[1]["children"][0]["stopped_at"]
    app.history.close()


def test_dashboard_family_api_and_pin(tmp_path):
    import urllib.request

    from blinkwise.app import App
    from blinkwise.config import Settings
    from blinkwise.ui.dashboard import DashboardServer

    app = App(Settings(), demo=True, ui=False, dashboard=False, tray=False,
              history_path=tmp_path / "h.sqlite", monitors=1)
    srv = DashboardServer(0, app.snapshot, app.history, app._on_dashboard_action, lambda: app.s,
                          app._on_settings, family=app.family)
    base = srv.start()

    def post(path, body):
        req = urllib.request.Request(base + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "X-Blinkwise-Token": srv.token})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)
    try:
        assert json.load(urllib.request.urlopen(base + "api/family"))["paired"] is False
        assert post("api/family", {"op": "set_pin", "pin": "4321"})[0] == 200
        st = json.load(urllib.request.urlopen(base + "api/settings"))
        assert st["parent_pin"] is True and st["family_token"] is False
        code, res = post("api/settings", {"stare_seconds": 12})
        assert code == 403 and res["pin_required"]
        assert post("api/settings", {"stare_seconds": 12, "pin": "4321"})[0] == 200
        assert post("api/action", {"action": "wipe"})[0] == 403
        assert post("api/action", {"action": "wipe", "pin": "4321"})[0] == 200
        assert post("api/settings", {"setup_done": True})[0] == 200        # setup still finishes
    finally:
        srv.stop()
        app.history.close()


def test_kids_mode_break_wording():
    from blinkwise.config import Settings
    from blinkwise.core.engine import Engine
    from blinkwise.core.events import BreakDue
    from blinkwise.core.simulate import Scenario, Simulation

    for profile, word in (("young", "count to 20"), ("adult", "6 m")):
        eng = Engine(Settings(profile=profile, micro_break_minutes=5), monitors=1)
        texts = [ev.exercise for f in Simulation(Scenario(duration_s=330, fps=10)).frames()
                 for ev in eng.step(f) if isinstance(ev, BreakDue)]
        assert texts and word in texts[0]

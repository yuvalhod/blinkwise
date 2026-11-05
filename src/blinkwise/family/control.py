"""The app side of family sharing and kids mode: what the dashboard's Family panel calls."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict
from urllib.parse import urlparse

from . import client
from . import payload as P

log = logging.getLogger(__name__)


class FamilyControl:
    def __init__(self, app):
        self.app = app
        self._uploader = None
        self._upload_lock = threading.Lock()

    @property
    def s(self):
        return self.app.s

    def pin_ok(self, pin: Any) -> bool:
        return client.check_pin(str(pin or ""), self.s.parent_pin)

    def get(self) -> Dict[str, Any]:
        s = self.s
        weeks = client.preview(self.app.history, s)      # shown before and while sharing
        return {
            "paired": bool(s.family_token),
            "server": urlparse(s.family_url).hostname if s.family_url else "",
            "name": s.family_name, "share_checkin": s.family_share_checkin, "removed": s.family_removed,
            "default_url": client.DEFAULT_URL, "pin_set": bool(s.parent_pin), "kids": s.profile == "young",
            "preview": [{"week": w["week_start"],
                         "rows": [r for r in P.describe(w) if r[0] != "Week starting"]}
                        for w in weeks],
        }

    def post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        op = body.get("op")
        s = self.s
        if op == "pair":
            try:
                res = client.pair(str(body.get("url") or client.DEFAULT_URL), str(body.get("code", "")))
            except client.FamilyError as e:
                raise ValueError(str(e)) from e
            self._save(family_url=res["url"], family_token=res["token"], family_name=res["name"],
                       family_removed=False,
                       family_share_checkin=bool(body.get("share_checkin", s.family_share_checkin)))
            self.upload_soon(force=True)
        elif op == "stop":
            if not self.pin_ok(body.get("pin")):
                raise PermissionError
            url, token = s.family_url, s.family_token
            self._save(family_url="", family_token="", family_name="", family_removed=False)
            if token:
                threading.Thread(target=client.unpair, args=(url, token), daemon=True).start()
        elif op == "share_checkin":
            self._save(family_share_checkin=bool(body.get("on")))   # the child's own choice
            self.upload_soon(force=True)
        elif op == "set_pin":
            if not self.pin_ok(body.get("old", "")):
                raise PermissionError
            new = str(body.get("pin", ""))
            if new and not client.valid_pin(new):
                raise ValueError("The PIN must be 4 to 8 digits.")
            self._save(parent_pin=client.hash_pin(new) if new else "")
        elif op == "dismiss_removed":
            self._save(family_removed=False)
        else:
            raise ValueError("unknown operation")
        self.app._publish_soon()
        return self.get()

    def _save(self, **fields) -> None:
        with self.app._settings_lock:
            for k, v in fields.items():
                setattr(self.s, k, v)
            try:
                self.s.save()
            except OSError:
                log.warning("could not save settings")

    # -------------------------------------------------------------- uploads
    def upload_soon(self, force: bool = False) -> None:
        threading.Thread(target=self.maybe_upload, kwargs={"force": force}, daemon=True).start()

    def maybe_upload(self, force: bool = False, send=client.upload) -> None:
        if self.app.history is None or not self.s.family_token:
            return
        with self._upload_lock:              # one upload at a time (pairing starts one too)
            if self._uploader is None:
                from ..config import data_dir
                self._uploader = client.Uploader(data_dir() / ".family_upload")
            status = self._uploader.run(self.app.history, self.s, time.time(), send=send, force=force)
        if status == 401:                     # the parent removed this computer
            self._save(family_url="", family_token="", family_name="", family_removed=True)
            self.app._publish_soon()

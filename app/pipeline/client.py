"""
The REST client the pipeline uses to read prod's event stream.

It does bulk, cursor-based reads. The cursor is the event timestamp, expressed
through prod's `dateFrom` filter.

A single keep-alive session is reused across calls, and the auth token is cached
and transparently refreshed whenever a request comes back 401. Credentials come
from the environment, which app.config loads from .env.mirror.
"""

import os

import httpx

PROD_API_BASE = os.environ.get("VEX_PROD_API_BASE", "https://inviteinstitutehub.org")


class ProdClientError(RuntimeError):
    pass


class ProdClient:
    """A thin wrapper over prod's /api/rabbitmq/vex_logs/ endpoint, handling
    token auth, a keep-alive session, and re-auth on a 401."""

    def __init__(self, base=PROD_API_BASE, connect_timeout=3.0, read_timeout=8.0):
        self.base = base
        self.timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
        self.session = httpx.Client()
        self._token = None

    def _call(self, method, path, **kw):
        """One request to prod. A timeout or a dropped connection is as transient
        as a 504, so it raises ProdClientError and the daemon backs off."""
        try:
            return getattr(self.session, method)(f"{self.base}{path}", timeout=self.timeout, **kw)
        except httpx.HTTPError as e:
            raise ProdClientError(f"prod unreachable: {e}") from e

    # -- auth -------------------------------------------------------------
    def _authenticate(self):
        user, pw = os.environ.get("PROD_USERNAME"), os.environ.get("PROD_PASSWORD")
        if not user or not pw:
            raise ProdClientError("Missing PROD_USERNAME/PROD_PASSWORD (.env.mirror or env).")
        resp = self._call("post", "/api/token/", json={"username": user, "password": pw})
        if resp.status_code != 200:
            raise ProdClientError(f"Auth failed ({resp.status_code}).")
        self._token = resp.json().get("token")
        return self._token

    def token(self):
        return self._token or self._authenticate()

    # -- reads ------------------------------------------------------------
    def _get(self, params):
        """Fetch one page of results. Retries once after re-authenticating if the
        first attempt returns 401; any other non-200 raises ProdClientError."""
        for token in (self.token(), None):
            headers = {"Authorization": f"Token {token or self._authenticate()}"}
            resp = self._call("get", "/api/rabbitmq/vex_logs/", headers=headers, params=params)
            if resp.status_code != 401:
                break
        if resp.status_code != 200:
            raise ProdClientError(f"prod API {resp.status_code}: {resp.text[:120]}")
        return resp.json().get("results", [])

    def page_by_time(self, date_from_iso, limit, offset):
        """A page of events across all students with received_at >= date_from.
        This is what a normal drain uses."""
        params = {"limit": limit, "offset": offset}
        if date_from_iso:
            params["dateFrom"] = date_from_iso
        return self._get(params)

    def page_student(self, student_id, limit, offset):
        """A page of one student's events, newest first. Used to backfill a
        student's history when they're added to the roster."""
        return self._get({"studentID": student_id, "limit": limit, "offset": offset})

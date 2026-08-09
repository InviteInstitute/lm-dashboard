"""
Researcher authentication for the API.

The whole origin is behind HTTP Basic Auth, so the browser shows its native
username/password dialog on first load and then attaches the cached credentials
to every same-origin request after that (including the SPA's /api calls and the
SSE stream). Credentials are verified against the researcher table with argon2;
a short-lived in-process cache keyed on the Authorization header keeps that argon2
verify from running on every single request.

Per-browser board isolation is orthogonal: the SPA sends a persistent localStorage
board id (X-Board-Id header, and a ?board_id= query param on the SSE stream), which
the routes map to a workspace -- see app/main.current_workspace_id.
"""

import base64
import os
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app import db

_hasher = PasswordHasher()


def hash_password(password):
    """Return an argon2 hash for a new/updated password."""
    return _hasher.hash(password)


def verify_password(password_hash, password):
    """True iff `password` matches the stored argon2 hash."""
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerificationError, InvalidHashError):
        return False


def authenticate(username, password):
    """Return {'id', 'username'} for valid credentials, else None."""
    r = db.get_researcher_by_username(username)
    if r and verify_password(r["password_hash"], password):
        return {"id": r["id"], "username": r["username"]}
    return None


def ensure_bootstrap_researcher():
    """INTERIM: seed one shared researcher login from the env-file prod creds
    (PROD_USERNAME / PROD_PASSWORD) so the dashboard is usable before real
    per-researcher accounts exist -- everyone signs in with those at the browser
    prompt. Idempotent (upsert), runs on startup. Replace with individual accounts
    (scripts/create_researcher.py) when you want stable per-person identities.
    No-op if the creds aren't set (e.g. the test env)."""
    user = os.environ.get("PROD_USERNAME")
    pw = os.environ.get("PROD_PASSWORD")
    if user and pw:
        db.upsert_researcher(user, hash_password(pw))


# Cache verified Authorization headers so the argon2 verify runs about once per
# credential rather than on every request. Keyed on the exact header value, so a
# changed password is a different key; entries expire after _AUTH_TTL seconds.
_auth_cache = {}  # authorization header -> (researcher_id, username, expires_at)
_AUTH_TTL = 300


def _resolve_basic(header):
    """Resolve an `Authorization: Basic ...` header to (researcher_id, username),
    or None. Verifies against the researcher table (cached)."""
    if not header.startswith("Basic "):
        return None
    now = time.monotonic()
    hit = _auth_cache.get(header)
    if hit and hit[2] > now:
        return hit[0], hit[1]
    try:
        user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
    except Exception:
        return None
    r = authenticate(user, pw)
    if not r:
        return None
    _auth_cache[header] = (r["id"], r["username"], now + _AUTH_TTL)
    return r["id"], r["username"]


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gate the whole origin with HTTP Basic Auth. A missing/invalid credential
    gets a 401 with WWW-Authenticate, which is what makes the browser show its
    native login dialog. On success the resolved researcher is stashed on
    request.state for the workspace resolver. /healthz stays open for probes."""

    async def dispatch(self, request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        resolved = await run_in_threadpool(_resolve_basic, request.headers.get("Authorization", ""))
        if not resolved:
            return Response(
                status_code=401, headers={"WWW-Authenticate": 'Basic realm="LM Dashboard"'}
            )
        request.state.researcher_id, request.state.username = resolved
        return await call_next(request)

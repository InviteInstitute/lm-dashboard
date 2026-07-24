"""
Researcher authentication for the API.

Replaces the old origin-wide HTTP Basic gate (whose password was the production
hub login) with per-researcher accounts. Each researcher logs in once; a signed
session cookie then carries their id (Starlette's SessionMiddleware signs it with
SESSION_SECRET, so it can't be forged). Password hashes are argon2.

The gate here protects the data API only: every `/api/*` route requires a logged-in
session except the public ones (`/api/login`). Non-`/api` paths -- the static SPA
bundle and `/healthz` -- stay open so the app can load and show its login screen;
all the actual data lives behind `/api`.
"""
import os

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app import db

_hasher = PasswordHasher()

# `/api/*` paths reachable without a session (compared with any trailing slash
# stripped). Everything else under /api requires a logged-in researcher.
_PUBLIC_API = {"/api/login"}


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
    per-researcher accounts and the login UI exist -- every researcher logs in
    with those. Idempotent (upsert), runs on startup. This is a stopgap: it means
    everyone shares one credential (and it's the prod-hub login), so replace it
    with individual accounts (scripts/create_researcher.py) once the login screen
    ships. No-op if the creds aren't set (e.g. the test env)."""
    user = os.environ.get("PROD_USERNAME")
    pw = os.environ.get("PROD_PASSWORD")
    if user and pw:
        db.upsert_researcher(user, hash_password(pw))


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Require a logged-in session for the data API. Reads the researcher id off
    the signed session cookie (populated by SessionMiddleware, which must sit
    outside this one). Trusting the signed id avoids a per-request DB lookup; a
    route that needs the full researcher resolves it via db.get_researcher_by_id."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        # Static SPA, /healthz, and other non-API routes are open.
        if not path.startswith("/api/"):
            return await call_next(request)
        if path.rstrip("/") in _PUBLIC_API:
            return await call_next(request)
        if request.session.get("researcher_id"):
            return await call_next(request)
        return JSONResponse({"detail": "authentication required"}, status_code=401)

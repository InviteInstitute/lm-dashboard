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

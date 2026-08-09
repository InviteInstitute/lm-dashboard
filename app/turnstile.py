"""
Cloudflare Turnstile gate for the API, replacing HTTP Basic Auth.

The dashboard's data is only reachable if you know a board's student IDs, so
this isn't about authenticating a person -- it's about keeping bots off the
API. A browser solves the widget once, the response token is verified
server-side against Cloudflare's siteverify, and success is remembered via a
signed cookie for COOKIE_MAX_AGE seconds, so solving is a one-time cost per
browser rather than per request.
"""

import httpx
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app import config

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
COOKIE_NAME = "ts_verified"
COOKIE_MAX_AGE = 12 * 3600  # re-solve the widget every 12h
VERIFY_PATH = "/api/turnstile/verify/"

_signer = TimestampSigner(config.SESSION_SECRET)


async def verify_turnstile(token, remote_ip):
    """True iff Cloudflare accepts this widget response token."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            SITEVERIFY_URL,
            data={
                "secret": config.TURNSTILE_SECRET,
                "response": token,
                "remoteip": remote_ip,
            },
        )
    return resp.status_code == 200 and resp.json().get("success") is True


def sign_cookie():
    """A fresh signed cookie value for a browser that just solved the widget."""
    return _signer.sign(b"ok").decode()


def cookie_is_valid(value):
    """True iff `value` is a cookie this process signed, within COOKIE_MAX_AGE."""
    if not value:
        return False
    try:
        _signer.unsign(value, max_age=COOKIE_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


class TurnstileGateMiddleware(BaseHTTPMiddleware):
    """Gates /api/* behind a solved Turnstile challenge. A missing/expired
    cookie gets a 403 the SPA recognizes and reacts to by showing the widget;
    /healthz, the static SPA shell, and the verify endpoint itself stay open."""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path == VERIFY_PATH:
            return await call_next(request)
        if not cookie_is_valid(request.cookies.get(COOKIE_NAME)):
            return JSONResponse({"error": "turnstile_required"}, status_code=403)
        return await call_next(request)

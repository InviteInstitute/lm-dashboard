"""
Origin-level access gate for remote serving (e.g. behind an ngrok tunnel).

When `DASHBOARD_USER` / `DASHBOARD_PASSWORD` are set, every request to the whole
origin (the UI and /api) must carry matching HTTP Basic credentials. The browser
shows its native login popup on the first page load, so there's nothing to build
and nothing for viewers to install; once they log in, the browser attaches the
cached credentials to every same-origin request after that, including the SPA's
/api calls.

It is OFF unless configured: with the two env vars unset (local dev on
localhost), the middleware is a no-op and nothing changes. This is intentionally
provider-independent, so it works behind ngrok, a Tailscale Funnel, or anything
else that just proxies HTTP to the local app.
"""
import base64
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# With DASHBOARD_AUTH=prod the remote login reuses the prod credentials
# (PROD_USERNAME / PROD_PASSWORD), so there's no second password to manage.
# Otherwise it uses the dedicated DASHBOARD_USER / DASHBOARD_PASSWORD. Either way
# the gate is off unless one of those pairs is set (local dev, tests).
if os.environ.get("DASHBOARD_AUTH") == "prod":
    USER = os.environ.get("PROD_USERNAME") or ""
    PASSWORD = os.environ.get("PROD_PASSWORD") or ""
else:
    USER = os.environ.get("DASHBOARD_USER") or ""
    PASSWORD = os.environ.get("DASHBOARD_PASSWORD") or ""


def _ok(header):
    """True if the Authorization header carries the configured Basic credentials.
    Uses compare_digest so a wrong guess can't be timed character by character."""
    if not header.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
    except Exception:
        return False
    return secrets.compare_digest(user, USER) and secrets.compare_digest(pw, PASSWORD)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gate the whole app with HTTP Basic Auth when configured; no-op otherwise."""

    async def dispatch(self, request, call_next):
        if not (USER and PASSWORD):
            return await call_next(request)
        if _ok(request.headers.get("Authorization", "")):
            return await call_next(request)
        return Response(status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="LM Dashboard"'})

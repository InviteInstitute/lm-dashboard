"""Process-wide settings, read once at import. Every value falls back to a
local-friendly default, so a fresh clone runs with no configuration; override
any of them through the environment when you need to."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root. This file is app/config.py, so two parents up is the repo top.
BASE_DIR = Path(__file__).resolve().parent.parent

# The daemon's production client needs credentials + a base URL; they live in
# .env.mirror. We load that file in BOTH processes for simplicity. The API never
# talks to prod, so the extra variables just sit there unused on that side.
load_dotenv(BASE_DIR / ".env.mirror")

# Postgres connection string (libpq URL), shared by the API and the daemon. This
# is the datastore; both processes open a pooled connection to it. Required in
# every real run -- the systemd units and scripts/start.sh load it from
# .env.mirror.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Secret used to sign the session cookie that carries a logged-in researcher's
# id (see app/auth.py). Required in any real deployment -- set a long random
# value in .env.mirror. The dev fallback keeps local runs and tests working but
# must never be used in production (sessions would be forgeable).
SESSION_SECRET = os.environ.get("SESSION_SECRET") or "dev-insecure-session-secret-change-me"

# Cross-origin allowlist for the browser. Defaults cover the Vite dev server's
# usual ports; comma-separated, blanks dropped.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")
    if o.strip()
]

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
# every real run -- compose loads it from .env.mirror.
DATABASE_URL = os.environ.get("DATABASE_URL")


# Goal recognition (agent-lm-packages goal_strategy) profiles each run in the
# worker and stores per-run goal evidence with explicit uncertainty. On by
# default; set GOAL_RECOGNITION_ENABLED=0 to disable the feed + storage entirely.
def _flag(name, default="1"):
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "")


GOAL_RECOGNITION_ENABLED = _flag("GOAL_RECOGNITION_ENABLED")
# The goal-progression timeline (cheap) and the sensor-test battery (runs 19 extra
# simulations per eligible run) are extra goal_strategy outputs. On by default;
# set GOAL_BATTERY_ENABLED=0 to shed the heavier one under load.
GOAL_TIMELINE_ENABLED = _flag("GOAL_TIMELINE_ENABLED")
GOAL_BATTERY_ENABLED = _flag("GOAL_BATTERY_ENABLED")
# The two battery-fed rollups: the purpose-1 goal claims (each goal banded from
# the battery, or derived from its indicators) and the PROVISIONAL purpose-2
# execution rubric (six dimensions, still under human validation upstream, so
# the UI labels it provisional). Both reuse the one battery run per program, so
# enabling them adds no extra simulations on top of GOAL_BATTERY_ENABLED.
GOAL_ROLLUP_ENABLED = _flag("GOAL_ROLLUP_ENABLED")
GOAL_RUBRIC_ENABLED = _flag("GOAL_RUBRIC_ENABLED")

# Secret used to sign the "this browser solved Turnstile" cookie (see
# app/turnstile.py). Required in any real deployment -- set a long random value
# in .env.mirror. The dev fallback keeps local runs and tests working but must
# never be used in production (the cookie would be forgeable).
SESSION_SECRET = os.environ.get("SESSION_SECRET") or "dev-insecure-session-secret-change-me"

# Cloudflare Turnstile secret key, used server-side to verify widget response
# tokens against Cloudflare's siteverify endpoint. Set in .env.mirror; unset
# means the gate can't verify anyone (see app/turnstile.py).
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET")

# Cross-origin allowlist for the browser. Defaults cover the Vite dev server's
# usual ports; comma-separated, blanks dropped.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(
        ","
    )
    if o.strip()
]

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

# The one SQLite file both processes share: the daemon is its sole writer, the
# API reads it, and WAL mode lets those happen concurrently.
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "db.sqlite3"))

# Cross-origin allowlist for the browser. Defaults cover the Vite dev server's
# usual ports; comma-separated, blanks dropped.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")
    if o.strip()
]

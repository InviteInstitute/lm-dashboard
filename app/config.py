"""Runtime configuration. Everything is env-overridable; sane local defaults."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root (app/ lives directly under it).
BASE_DIR = Path(__file__).resolve().parent.parent

# Prod credentials + endpoint for the ingestion daemon's client live here.
# Loaded for both processes; harmless for the API (it never calls prod).
load_dotenv(BASE_DIR / ".env.mirror")

# The SQLite file the API reads and the daemon writes (shared via WAL).
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "db.sqlite3"))

# Browser origins allowed to call the API (the Vite dev server).
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",")
    if o.strip()
]

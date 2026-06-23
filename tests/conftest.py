"""Shared test fixtures.

Every test runs against a throwaway SQLite file (DB_PATH is redirected to a temp
dir *before* any app module is imported, so the real db.sqlite3 is never
touched). Each test gets a clean schema + empty tables + a fresh in-memory
worker registry, so tests can't leak state into each other.
"""
import os
import tempfile

# Redirect the DB before app.config reads it. load_dotenv(override=False) in
# config.py won't clobber an env var we've already set, so this wins.
_TMP = tempfile.mkdtemp(prefix="lmd_tests_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.sqlite3")

import pytest                                    # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

from app import db                                # noqa: E402
from app.main import app as fastapi_app           # noqa: E402
from app.pipeline import workers                  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Recreate the schema and truncate every table before each test, and clear
    the daemon's in-memory worker registry (a module global that would otherwise
    persist across tests)."""
    db.init_db()
    # db.py keeps ONE shared process connection; never close it here (write_txn
    # commits on the shared handle). Just truncate every table for a clean slate.
    with db.write_txn() as con:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            if not t.startswith("sqlite_"):
                con.execute(f"DELETE FROM {t}")
    # The control-flag cache is a module global with a 200ms TTL; clear it so a
    # flag set in one test can't leak into the next (the daemon reads through it).
    db._meta_cache.clear()
    workers.reset()
    yield


@pytest.fixture
def client():
    """A FastAPI TestClient bound to the temp DB."""
    return TestClient(fastapi_app)


@pytest.fixture
def seed_state():
    """Helper: upsert a materialized student_state row and return the studentID."""
    def _seed(sid="stu1", **overrides):
        payload = {
            "classCode": "C1",
            "current_state": 1,
            "state_label": "explorer",
            "stuck": False,
            "consecutive_stuck": 0,
            "run_count": 2,
            "event_count": 7,
            "runs": {"runs": [{"index": 0, "hmm_state": None, "change_score": None}],
                     "obs_labels": {}, "run_count": 2},
            "episodes": {"events": [{"eventType": "runProject"}], "episodes": [],
                         "pauses": [], "event_count": 7},
            "playground_prompt": "[Active] events_whenStarted { motor_on }",
            "playground_time": db.now(),
            "last_event_id": 7,
            "last_event_time": db.now(),
        }
        payload.update(overrides)
        db.upsert_student_state(sid, payload)
        return sid
    return _seed

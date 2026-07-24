"""Shared test fixtures.

Every test runs against a dedicated Postgres database (DATABASE_URL is redirected
to it *before* any app module is imported, so dev/prod data is never touched).
The test DB defaults to the dev DATABASE_URL with the database name swapped to
`lm_dashboard_test`; override with TEST_DATABASE_URL. Create it once with:
    sudo -u postgres createdb -O lmdash lm_dashboard_test
Each test gets a clean schema + empty tables (identity counters reset so ids
start at 1) + a fresh in-memory worker registry, so tests can't leak state.
"""
import os

from dotenv import load_dotenv

# Point the data layer at the test database before app.config reads DATABASE_URL.
# config.py's load_dotenv(override=False) won't clobber an env var we set first.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.mirror"))
_test_url = os.environ.get("TEST_DATABASE_URL")
if not _test_url:
    _base = os.environ["DATABASE_URL"]
    _test_url = _base.rsplit("/", 1)[0] + "/lm_dashboard_test"
os.environ["DATABASE_URL"] = _test_url

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
    # Truncate every app table for a clean slate. RESTART IDENTITY resets the id
    # sequences so ids start at 1 each test (matching the old fresh-file behavior
    # tests rely on); CASCADE handles the vex_log -> message foreign key.
    with db.write_txn() as con:
        tables = [r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")]
        if tables:
            con.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
    # The control-flag cache is a module global with a 200ms TTL; clear it so a
    # flag set in one test can't leak into the next (the daemon reads through it).
    db._meta_cache.clear()
    workers.reset()
    workers.set_session_cutoff(None)   # module global; don't leak a cutoff between tests
    yield


@pytest.fixture
def anon_client():
    """An unauthenticated TestClient (no session) -- for exercising the auth gate."""
    return TestClient(fastapi_app)


@pytest.fixture
def client():
    """A TestClient logged in as a throwaway researcher, so the data API (gated by
    SessionAuthMiddleware) is reachable. Most tests want this."""
    from app import auth
    db.upsert_researcher("tester", auth.hash_password("secret"))
    c = TestClient(fastapi_app)
    resp = c.post("/api/login/", json={"username": "tester", "password": "secret"})
    assert resp.status_code == 200, resp.text
    return c


@pytest.fixture
def seed_state():
    """Helper: upsert a materialized student_state row and return the studentID."""
    def _seed(sid="stu1", **overrides):
        payload = {
            "classCode": "C1",
            "run_count": 2,
            "event_count": 7,
            "runs": {"runs": [{"index": 0, "edit_distance": None, "ts": None}],
                     "run_count": 2},
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

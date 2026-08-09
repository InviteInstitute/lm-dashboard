---
description: What the test suite covers and how to run the backend (pytest) and frontend (vitest) tests.
---

# Running the Tests

The project ships with tests on both sides: a Python suite for the backend (the
data layer, pipeline, and API) and a JavaScript suite for the dashboard. They run
independently, so you can run whichever side you're working on.

## What's Covered

The backend tests exercise the parts where the real logic lives: the Postgres data
layer (the datetime contract and the zip export), the ingestion poller, the
per-student workers, the APTED edit-distance computation, the five trigger rules and
their history, identity-switch detection, the episode segmenter, the block humanizer,
the live-stream change signal, the failed-write outbox, the auth gate, the
workspace/per-browser isolation and the daemon's fan-out, and every API endpoint
through a test client.

The frontend tests cover the dashboard's formatting helpers and render the real
component against a mocked API to check that students, alerts, the trigger-history
grid, the toggle buttons, and the resilient-write path (retry, outbox park, red
toast) behave.

You don't need to read every case to trust them. If they're green, the contract
the daemon and dashboard depend on is intact.

!!! tip "Or just run make test"
    `make test` runs both suites in one go, and `make lint` / `make format` run the ruff
    and prettier checks. See [Development](development.md) for the full command vocabulary
    and the CI setup.

## Backend (pytest)

The test tools (`pytest`, `pytest-cov`, `ruff`) are the dev extras in `pyproject.toml`, so
`pip install -e '.[dev]'` (or `make install`) pulls them in. The suite needs a **Postgres
it can reach** — it connects using `DATABASE_URL` with the database name swapped to
**`lm_dashboard_test`** (override with `TEST_DATABASE_URL`), and it truncates that database
between tests, so your real data is never touched.

Point `DATABASE_URL` at a local Postgres (the prod compose DB is internal, so for
running tests use a Postgres exposed on a host port — e.g. a small `postgres` container
on `localhost:5432`), create the test database once, then run from the repo root:

```bash
createdb -O lmdash lm_dashboard_test    # once
pytest
```

For a coverage report:

```bash
pytest --cov=app --cov-report=term-missing
```

The suite is quick: there's no ML model to load and no heavy scientific dependencies
to import, just FastAPI, psycopg, and APTED.

## Frontend (vitest)

From the `frontend/` directory:

```bash
cd frontend
npm install
npm test
```

That runs the suite once and exits. During development you can use
`npx vitest` instead to keep it watching and re-running on save.

---
description: What the tests cover, and how to run the backend (pytest) and frontend (vitest) suites.
---

# Running The Tests

There are two suites. A Python suite covers the backend (the data layer, the daemon and the API),
and a JavaScript suite covers the dashboard. They run apart from each other, so you can run the
side you're working on.

`make test` runs both, and `make lint` and `make format-check` run ruff and prettier. See
[Development](development.md) for every command and for CI.

## What They Cover

The backend tests cover the Postgres layer (the timestamp rule, the export and reset), the poller
and its cursor, the per-student workers, the APTED edit distance, the five triggers and their
history, identity switches, the episode segmenter, the readable program, the live stream's change
signal, the outbox, the Turnstile gate, ZANY sources, goal evidence, board isolation and the
daemon's fan-out across boards. Every API endpoint is called through a test client.

The frontend tests cover the time and status helpers (`src/lib/*.test.js`). They also render the
whole dashboard against a mocked API (`src/CohortDashboard.test.jsx`) and check students, alerts,
identity switches and their toasts, the student sheet and its goal evidence, the toggles, ZANY
sources and the safe-write path (retry, outbox and red toast).

## Backend (pytest)

The dev extras in `pyproject.toml` hold the test tools (`pytest`, `pytest-cov`, `ruff` and `httpx2`
for the API test client), so `make install` brings them in.

The suite needs a Postgres it can reach. It uses `DATABASE_URL` with the database name changed to
`lm_dashboard_test`, or `TEST_DATABASE_URL` if you set it. It empties that database between tests,
so your real data is never touched.

The compose `db` service has no port on the host, so a throwaway container is the quickest way.

```bash
docker run -d --rm --name lmdash-test -e POSTGRES_USER=lmdash -e POSTGRES_PASSWORD=lmdash \
  -e POSTGRES_DB=lm_dashboard_test -p 127.0.0.1:55432:5432 postgres:18
export DATABASE_URL=postgresql://lmdash:lmdash@127.0.0.1:55432/lm_dashboard_test
pytest
```

For a coverage report, run this.

```bash
pytest --cov=app --cov-report=term-missing
```

The suite is quick, since there is no model to load and no heavy scientific package to import.

## Frontend (vitest)

```bash
cd frontend
npm install
npm test
```

That runs the suite once and exits. `npx vitest` keeps it watching and runs it again on every save.

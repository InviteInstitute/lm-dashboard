---
description: What the test suite covers and how to run the backend (pytest) and frontend (vitest) tests.
---

# Running the Tests

The project ships with tests on both sides: a Python suite for the backend (the
data layer, pipeline, and API) and a JavaScript suite for the dashboard. They run
independently, so you can run whichever side you're working on.

## What's Covered

The backend tests exercise the parts where the real logic lives: the SQLite data
layer (including the datetime contract and CSV export), the ingestion poller, the
per-student workers, the trigger rules, the episode segmenter, the strategy HMM
(against the real trained model), and every API endpoint through a test client.

The frontend tests cover the dashboard's formatting helpers and render the real
component against a mocked API to check that students, alerts, and the toggle
buttons behave.

You don't need to read every case to trust them. If they're green, the contract
the daemon and dashboard depend on is intact.

## Backend (pytest)

The test tools (`pytest`, `pytest-cov`, `httpx`) are in `requirements.txt`, so if
you've installed the app you already have them. Run the suite from the repo root:

```bash
pytest
```

For a coverage report:

```bash
pytest --cov=app --cov-report=term-missing
```

!!! note
    The first run takes a little longer than you'd expect for a small suite. That's
    the `hmmlearn` / `scikit-learn` import and loading the trained model, which the
    strategy tests run for real rather than mocking.

The tests use a throwaway SQLite database in a temp directory, so your local
`db.sqlite3` is never touched.

## Frontend (vitest)

From the `frontend/` directory:

```bash
cd frontend
npm install
npm test
```

That runs the suite once and exits. During development you can use
`npx vitest` instead to keep it watching and re-running on save.

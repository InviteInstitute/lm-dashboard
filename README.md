# LUC Cohort Dashboard

A live "who needs help" dashboard for a cohort of students coding in the VEX
block environment. It mirrors VEX telemetry, infers each student's coding
**strategy** with an HMM, segments their session into **episodes**, and raises
**intervention triggers** (wheel-spinning, idle, big rewrite) for a teacher to act on.

## Architecture

Three small pieces, no framework bloat:

```
app/
  main.py            FastAPI read API (4 endpoints) — reads materialized state only
  db.py              raw-sqlite3 data layer (schema, queries, JSON/datetime handling)
  config.py          env-derived settings
  smart_delta_engine.py   block-diff → LLM playground prompt
  strategy_hmm/      events → change scores → HMM latent states (+ trained model.pkl)
  pipeline/          the ingestion + inference daemon (the only DB writer)
    client.py        authenticated bulk reader of the prod VEX hub
    poller.py        idempotent, cursor-based ingest of raw logs
    workers.py       per-student in-memory workers → materialize student_state
    triggers.py      threshold rules → trigger_event feed
    daemon.py        the tick loop  (python -m app.pipeline)
frontend/            Vite + React single-screen dashboard
scripts/migrate_db.py   one-shot: rename legacy tables + VACUUM
```

**Two processes, one SQLite file (WAL):** the **daemon** ingests and computes and
is the *only* writer of derived state; the **API** only reads it (and owns the
tracked-student allowlist + acknowledgements). The API needs no ML dependencies.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.mirror   # fill in PROD_USERNAME / PROD_PASSWORD (daemon only)
```

First run only — migrate the existing DB to the clean table names and reclaim space:

```bash
python scripts/migrate_db.py
```

## Run

```bash
# API  (http://localhost:8000)
uvicorn app.main:app --port 8000 --reload

# ingestion + inference daemon (run exactly one instance)
python -m app.pipeline            # --backfill-hours N to bound the first drain

# frontend (http://localhost:3000)
cd frontend && npm install && npm run dev
```

Add a student ID in the dashboard's "Track a student" box; the daemon backfills
their history, materializes their state, and they start appearing in the feed.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/api/triggers/` | active + recently-resolved trigger feed |
| POST | `/api/triggers/ack/` | dismiss a trigger (`{studentID}` or `{id}`) |
| GET  | `/api/tracked/` | tracked-student roster |
| POST | `/api/tracked/` | track `{studentID}` / untrack `{studentID, remove:true}` |
| GET  | `/api/student_states/?students=<id>` | materialized per-student detail |

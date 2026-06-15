---
description: Every environment variable and CLI flag for the API and the ingestion daemon.
---

# Configuration

All settings are environment variables. Put the daemon's credentials in
`.env.mirror`; the rest have sane local defaults.

## Environment variables

| Variable | Used by | Default | Purpose |
|---|---|---|---|
| `PROD_USERNAME` / `PROD_PASSWORD` | daemon | — | auth to the prod server |
| `VEX_PROD_API_BASE` | daemon | `https://inviteinstitutehub.org` | prod server base URL |
| `DB_PATH` | both | `db.sqlite3` | SQLite file location |
| `CORS_ORIGINS` | API | `http://localhost:3000,http://localhost:5173` | allowed dashboard origins |
| `PIPELINE_INTERVAL` | daemon | `0.5` | base seconds per tick while events flow |
| `PIPELINE_IDLE_MAX` | daemon | `5.0` | idle-backoff ceiling (poll gap when quiet) |
| `PIPELINE_PAGE_LIMIT` | daemon | `500` | events fetched per page |
| `PIPELINE_BACKFILL_HOURS` | daemon | `24` | on first run only, bound the initial drain to the last N hours (`<= 0` = replay all history) |

!!! note
    `.env.mirror` is loaded by both processes but only the daemon uses the prod
    credentials. It is harmless for the API, which never calls prod.

## CLI flags

The daemon settings are also available as flags, which override the environment:

```bash
python -m app.pipeline --interval 1 --idle-max 8 --backfill-hours 2
```

The full flag set: `--interval`, `--idle-max`, `--limit` (events per page),
`--overlap` (cursor overlap seconds), `--backfill-hours`. Run
`python -m app.pipeline --help` for the inline reference.

## Polling and idle backoff

While students are active the daemon polls every `PIPELINE_INTERVAL` seconds.
When nothing is happening it backs off exponentially toward `PIPELINE_IDLE_MAX`
(for example 0.5 → 1 → 2 → 4 → 5s) so it does not hammer prod with empty
requests, and snaps back to fast the moment activity resumes.

!!! tip
    Poll load is a function of **event volume**, not the number of tracked
    students. A quiet cohort barely touches prod regardless of roster size.

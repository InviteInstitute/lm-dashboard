---
description: Every environment variable and CLI flag for the API and the ingestion daemon.
---

# Configuration

Everything is configured through environment variables. Put the daemon's
credentials in `.env.mirror`, and leave the rest alone unless you have a reason;
the defaults are sane for local use.

## Environment variables

| Variable | Used by | Default | What it does |
|---|---|---|---|
| `PROD_USERNAME` / `PROD_PASSWORD` | daemon | (none) | auth to the prod server |
| `VEX_PROD_API_BASE` | daemon | `https://inviteinstitutehub.org` | prod server base URL |
| `DB_PATH` | both | `db.sqlite3` | where the SQLite file lives |
| `CORS_ORIGINS` | API | `http://localhost:3000,http://localhost:5173` | allowed dashboard origins |
| `PIPELINE_INTERVAL` | daemon | `0.5` | base seconds per tick while events are flowing |
| `PIPELINE_IDLE_MAX` | daemon | `5.0` | the idle-backoff ceiling (how far the poll gap stretches when it's quiet) |
| `PIPELINE_PAGE_LIMIT` | daemon | `500` | events fetched per page |
| `PIPELINE_BACKFILL_HOURS` | daemon | `24` | on the first run only, how far back the initial drain goes (`<= 0` means replay all history) |

!!! note
    Both processes load `.env.mirror`, but only the daemon actually uses the prod
    credentials. It's harmless for the API, which never calls prod.

## CLI flags

The daemon settings are also flags, and the flags win over the environment:

```bash
python -m app.pipeline --interval 1 --idle-max 8 --backfill-hours 2
```

The full set is `--interval`, `--idle-max`, `--limit` (events per page),
`--overlap` (cursor overlap seconds), and `--backfill-hours`. Run `python -m
app.pipeline --help` for the inline reference.

## Polling and idle backoff

While students are active, the daemon polls every `PIPELINE_INTERVAL` seconds. When
nothing's happening, it backs off exponentially toward `PIPELINE_IDLE_MAX` (so
0.5 → 1 → 2 → 4 → 5s) instead of hammering prod with empty requests, and it snaps
right back to fast the moment activity returns.

!!! tip
    Poll load tracks event volume, not roster size. A quiet cohort barely touches
    prod no matter how many students you're tracking.

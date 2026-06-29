---
description: Every environment variable and CLI flag for the API and the ingestion daemon.
---

# Configuration

Everything is configured through environment variables. Put the daemon's credentials
in `.env.mirror`, and leave the rest alone unless you have a reason; the defaults are
sane for local use.

## Environment Variables

| Variable | Used By | Default | What It Does |
|---|---|---|---|
| `PROD_USERNAME` / `PROD_PASSWORD` | daemon | (none) | auth to the prod server |
| `VEX_PROD_API_BASE` | daemon | `https://inviteinstitutehub.org` | prod server base URL |
| `DB_PATH` | both | `db.sqlite3` | where the SQLite file lives |
| `CORS_ORIGINS` | API | `http://localhost:3000,http://localhost:5173` | allowed dashboard origins |
| `PIPELINE_INTERVAL` | daemon | `0.5` | base seconds per tick while events are flowing |
| `PIPELINE_IDLE_MAX` | daemon | `5.0` | the idle-backoff ceiling (how far the poll gap stretches when it's quiet) |
| `PIPELINE_PAGE_LIMIT` | daemon | `500` | events fetched per page |
| `PIPELINE_BACKFILL_HOURS` | daemon | `24` | on the first run only, how far back the initial drain goes (`<= 0` means replay all history) |
| `PIPELINE_REQUIRE_VIEWER` | daemon | `0` (off) | when set, arms the dead-man's switch: prod polling pauses whenever no dashboard is open |

!!! note
    Both processes load `.env.mirror`, but only the daemon actually uses the prod
    credentials. It's harmless for the API, which never calls prod.

## CLI Flags

The daemon's settings are also available as flags, and a flag wins over the matching
environment variable:

```bash
python -m app.pipeline --interval 1 --idle-max 8 --backfill-hours 2
```

The full set is `--interval`, `--idle-max`, `--limit` (events per page), `--overlap`
(cursor overlap seconds), `--backfill-hours`, and `--require-viewer` (arm the dead-man's
switch). Run `python -m app.pipeline --help` for the inline reference.

## Polling And Idle Backoff

While students are active, the daemon polls every `PIPELINE_INTERVAL` seconds. When
nothing's happening, it backs off exponentially toward `PIPELINE_IDLE_MAX` (so
0.5 → 1 → 2 → 4 → 5s) instead of hammering prod with empty requests, and it snaps
right back to fast the moment activity returns.

!!! tip
    Poll load tracks event volume, not roster size. A quiet cohort barely touches
    prod no matter how many students you're tracking.

## The Dead-Man's Switch

Idle backoff slows prod polling when nothing's happening, but it never stops. The
dead-man's switch does: with `--require-viewer` (or `PIPELINE_REQUIRE_VIEWER=1`) the
daemon only polls prod while a dashboard is actually open.

It works off a heartbeat. The read API stamps `viewer_last_seen` every time the dashboard
fetches the grid, and the frontend stops polling the moment its tab is hidden, so a fresh
stamp means someone is genuinely looking. Each tick the daemon checks that stamp: if it's
gone stale, prod polling pauses, and it resumes on the next tick once a dashboard polls
again. The staleness window is the `VIEWER_PRESENT_SECONDS` constant in
`app/constants.py` (90 seconds), which is the one knob here that lives in code rather than
an environment variable, since it rarely needs touching.

`scripts/start.sh --remote` arms this automatically, so a session served over ngrok stops
hitting prod whenever the last viewer closes or backgrounds their tab. It's left off for
local runs, where you want collection to continue whether or not someone is watching.

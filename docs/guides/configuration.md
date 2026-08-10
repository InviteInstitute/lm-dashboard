---
description: Environment variables, accounts, and CLI flags for the API and the ingestion daemon.
---

# Configuration

Configuration is split across two gitignored files:

- **`.env`** - read by `docker compose` itself. Holds `POSTGRES_PASSWORD`. Compose
  uses it for the `db` service and to build `DATABASE_URL`.
- **`.env.mirror`** - the app's own secrets (loaded by both the API and the daemon).

## Environment Variables

| Variable | Where | Default | What It Does |
|---|---|---|---|
| `POSTGRES_PASSWORD` | `.env` (compose) | (none) | password for the `db` service, compose folds it into `DATABASE_URL` |
| `DATABASE_URL` | app | (compose sets it) | Postgres connection string. Under compose it points at the `db` service. Set it yourself only for a non-compose venv run |
| `PROD_USERNAME` / `PROD_PASSWORD` | daemon | (none) | auth to the prod server (unrelated to the dashboard's own bot gate) |
| `VEX_PROD_API_BASE` | daemon | `https://inviteinstitutehub.org` | prod server base URL |
| `TURNSTILE_SECRET` | API | (none) | Cloudflare Turnstile secret key, verified against the public site key baked into the frontend build |
| `SESSION_SECRET` | API | insecure dev default | signs the "this browser solved Turnstile" cookie. Set a long random value in any real deployment |
| `CORS_ORIGINS` | API | `http://localhost:3000,http://localhost:5173` | allowed dashboard origins (dev only, prod is same-origin) |
| `PIPELINE_INTERVAL` | daemon | `0.5` | base seconds per tick while events are flowing |
| `PIPELINE_IDLE_MAX` | daemon | `5.0` | idle-backoff ceiling (how far the poll gap stretches when it's quiet) |
| `PIPELINE_PAGE_LIMIT` | daemon | `500` | events fetched per page |
| `PIPELINE_BACKFILL_HOURS` | daemon | `24` | on the first run only, how far back the initial drain goes (`<= 0` = replay all history) |
| `PIPELINE_REQUIRE_VIEWER` | daemon | `0` (dev) / `1` (prod compose) | arms the per-board dead-man's switch (below) |

## Access

The dashboard is public - reachable by anyone who knows a board's student IDs - so
there's no login. The only gate is **Cloudflare Turnstile**, which keeps bots (not
people) off the API: a browser solves the widget once, and success is remembered via
a signed cookie for 12 hours (`app/turnstile.py`). Losing/clearing that cookie just
means solving the widget again, not signing back in - there's nothing to log out of.

Each browser is isolated into its own **board** via a persistent id it stores in
`localStorage` and sends as `X-Board-Id`. A request with no board id falls back to
one shared default workspace.

## CLI Flags (daemon)

The daemon's settings are also flags, and a flag wins over the matching env var:

```bash
python -m app.pipeline --interval 1 --idle-max 8 --backfill-hours 2
```

The full set is `--interval`, `--idle-max`, `--limit` (events per page), `--overlap`
(cursor overlap seconds), `--backfill-hours`, and `--require-viewer`. Run
`python -m app.pipeline --help` for the inline reference.

## Polling And Idle Backoff

While students are active, the daemon polls every `PIPELINE_INTERVAL` seconds. When
nothing's happening, it backs off exponentially toward `PIPELINE_IDLE_MAX` (so
0.5 → 1 → 2 → 4 → 5s) instead of hammering prod, and snaps back to fast the moment
activity returns.

!!! tip
    Poll load tracks event volume, not roster size - and a student watched by
    several boards is still polled only once (the daemon ingests the union of all
    boards' rosters into one shared mirror).

## The Dead-Man's Switch

Per board: the dead-man's switch stops prod polling for a board while nobody is watching it.
With `--require-viewer` (or `PIPELINE_REQUIRE_VIEWER=1`, the prod default) the daemon
only polls a board's students while that board's dashboard is actually open.

It works off a heartbeat. The read API stamps a per-board `viewer_last_seen` while a
dashboard holds the live stream open (on connect and every ~10s) and on each grid
fetch. The frontend closes the stream when its tab is hidden. Each tick the daemon
polls prod only for the students on **live** boards (polling enabled and a fresh
viewer). The staleness window is the `VIEWER_PRESENT_SECONDS` constant in
`app/constants.py` (90 seconds).

In the prod compose file the daemon runs with `PIPELINE_REQUIRE_VIEWER=1`, so a
served deployment stops hitting prod for any board whose dashboard is closed. Dev
leaves it off so a local run polls as soon as a board has students.

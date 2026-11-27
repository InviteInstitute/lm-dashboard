---
description: Environment variables, daemon flags, access and the dead-man's switch.
---

# Configuration

Settings live in two files, and git ignores both.

- `.env` is read by `docker compose` itself. It holds `POSTGRES_PASSWORD`, which compose uses for
  the `db` service and to build `DATABASE_URL`.
- `.env.mirror` holds the app's own secrets. The API and the daemon both load it.

`app/config.py` reads every setting once, at import. Each one has a default that works locally, so a
fresh clone runs without any of them except the database and the Reflecks login.

## Environment Variables

| Variable | Read by | Default | What it does |
|---|---|---|---|
| `POSTGRES_PASSWORD` | compose | none | the `db` service's password. Compose puts it into `DATABASE_URL` |
| `DB_DATA` | compose | `pgdata`, a compose volume | where Postgres keeps its files. The INVITE server sets `/data/lm-dashboard/postgres`. Copy the data there with the database stopped before you set it, or Postgres starts empty |
| `DATABASE_URL` | API and daemon | set by compose | the Postgres connection string. Set it yourself only when you run outside compose |
| `PROD_USERNAME`, `PROD_PASSWORD` | daemon | none | the daemon's Reflecks login, which has nothing to do with the dashboard's own bot check |
| `VEX_PROD_API_BASE` | daemon | `https://inviteinstitutehub.org` | the Reflecks server |
| `TURNSTILE_SECRET` | API | none | the Cloudflare Turnstile secret key. It pairs with the public site key in `frontend/src/constants.js` |
| `SESSION_SECRET` | API | an unsafe dev value | signs the Turnstile and ZANY unlock cookies. Set a long random value on any real server |
| `CORS_ORIGINS` | API | `http://localhost:3000,http://localhost:5173` | the origins a browser may call from. Only development needs it, since a served dashboard has the same origin as the API |
| `PIPELINE_INTERVAL` | daemon | `0.5` | seconds per tick while events are flowing |
| `PIPELINE_IDLE_MAX` | daemon | `5.0` | the longest wait between polls when nothing is happening |
| `PIPELINE_PAGE_LIMIT` | daemon | `500` | events per page from Reflecks |
| `PIPELINE_REQUIRE_VIEWER` | daemon | `1` in `compose.yml`, `0` in development | arms the dead-man's switch (below) |
| `ZANY_LOG_DSN` | API and daemon | none, so ZANY is off | ATLAS-invite's ZANY log store, read-only, like `postgresql://lmdash_reader:...@/zany?host=/var/run/postgresql`. The INVITE server keeps it in `/etc/lm-dashboard/zany.env`, which compose reads when it exists |
| `ATLAS_URL` | API | `https://zany.inviteai.org` | ATLAS-invite, which checks the research login that unlocks ZANY |
| `GOAL_RECOGNITION_ENABLED` | daemon and API | `1` | profiles each Castle Crashers run for goal evidence. `0` turns off the profiling, its storage and the sheet's Goal Evidence section |
| `GOAL_TIMELINE_ENABLED` | daemon | `1` | also records each run's goal timeline, which is cheap |
| `GOAL_BATTERY_ENABLED` | daemon | `1` | also runs the sensor test battery, 19 extra simulations for each program that reads a sensor. `0` sheds the heaviest goal work under load |
| `GOAL_ROLLUP_ENABLED` | daemon | `1` | also rolls the battery up into one claim per goal |
| `GOAL_RUBRIC_ENABLED` | daemon | `1` | also scores the provisional execution rubric |

The goal flags are off for any of `0`, `false`, `no` or an empty value.

## Access

The dashboard is public, and there is no login. Anyone who knows a student ID can track that
student. The only gate is Cloudflare Turnstile, which keeps bots off the API. A browser solves the
widget once, and a signed `ts_verified` cookie remembers it for 12 hours (`app/turnstile.py`).
Losing the cookie only means solving the widget again.

Each browser keeps its board ID in local storage and sends it as the `X-Board-Id` header. A request
without one acts on a shared default board.

ZANY's logs need the research login on top of that. See [Sources](../concepts/sources.md#the-research-login).

## Daemon Flags

Every daemon setting is also a flag, and a flag wins over its environment variable.

```bash
python -m app.pipeline --interval 1 --idle-max 8
```

The flags are `--interval`, `--idle-max`, `--limit` (events per page), `--overlap` (cursor overlap
in seconds, default 2) and `--require-viewer`. `python -m app.pipeline --help`
describes each.

## Polling And Idle Backoff

While students are active, the daemon polls every `PIPELINE_INTERVAL` seconds. When nothing is
happening, it doubles the wait each tick up to `PIPELINE_IDLE_MAX`, so 0.5, 1, 2, 4 and then 5
seconds. The first sign of activity brings it straight back to 0.5.

!!! tip
    Poll load follows how much is happening, not the size of the roster. A student on several
    boards is still polled once, since the daemon reads the union of all rosters into one shared
    copy.

## The Dead-Man's Switch

The dead-man's switch stops polling production for a board that nobody is watching. With
`--require-viewer` (or `PIPELINE_REQUIRE_VIEWER=1`, the default in `compose.yml`), the daemon only
polls a board's students while that board's dashboard is open.

It works from a heartbeat. The API stamps the board's `viewer_last_seen` when a dashboard opens
the live stream, every 10 seconds while it stays open, and on every fetch of the card grid. The
dashboard closes the stream when its tab is hidden. Each tick, the daemon polls only for students
on boards that are live, meaning polling is on and the stamp is less than `VIEWER_PRESENT_SECONDS`
(90 seconds, in `app/constants.py`) old.

So a served deployment stops calling production for any board whose dashboard is closed.
Development turns the switch off, so a local board is polled as soon as it has students.

The switch and the **Pause polling** button are separate. The daemon polls a board only when its
polling is on and someone is watching it.

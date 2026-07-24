---
description: Bring up the whole stack (Postgres, API, daemon) with one docker compose command.
---

# Quickstart

The whole stack — Postgres, the read API (which also serves the dashboard), and the
ingestion daemon — runs from one `docker compose` file, the same on your laptop and
in production.

## Before You Start

!!! info
    You only need **Docker** (Docker Desktop on macOS/Windows, or Docker + the
    Compose v2 plugin on Linux). The daemon also needs network access to the
    Reflecks production server and a real account on it.

## Configure

Two small files, both gitignored:

1.  **App secrets** — copy the example and fill it in:

    ```bash
    cp .env.example .env.mirror     # set PROD_USERNAME / PROD_PASSWORD
    ```

    `PROD_USERNAME` / `PROD_PASSWORD` are the daemon's Reflecks login. They also
    seed the interim shared dashboard login (see [Using the dashboard](guides/using-the-dashboard.md)).

2.  **Database password** for compose:

    ```bash
    echo "POSTGRES_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_hex(16))')" > .env
    ```

Compose builds `DATABASE_URL` for you (pointing at the `db` service), so you don't
set it yourself. The schema is created automatically on API startup — there is no
separate migration step.

## Run

```bash
docker compose up -d
```

That's it. In **dev**, compose auto-loads `compose.override.yml`, which adds:

- the dashboard under **Vite with hot-reload** at [http://localhost:3000](http://localhost:3000)
  (it proxies `/api` to the API), and
- the API and daemon running with `--reload`, so code changes restart instantly.

In **production**, run the base file only so the API serves the pre-built dashboard
on `:8000` (put a reverse proxy / TLS in front of it):

```bash
docker compose -f compose.yml up -d
```

!!! warning
    Exactly one daemon runs (compose starts one). The cursor and idempotency logic
    assume a single writer.

Handy commands:

```bash
docker compose ps                    # status
docker compose logs -f daemon        # follow a service (api / daemon / db)
docker compose down                  # stop everything
```

## Sign In and Track Your First Student

Open the dashboard. Your **browser prompts for a username and password** — sign in
with `PROD_USERNAME` / `PROD_PASSWORD`. Then type a student ID into **Track a
student**: the daemon backfills their recent history, materializes their state, and
their card appears within a tick or two.

!!! note "Each browser is its own board"
    Under the shared login, every browser gets its own isolated board (roster,
    notes, picks). For stable per-person boards across devices, create named
    accounts with `scripts/create_researcher.py` — see
    [Configuration](guides/configuration.md).

!!! success
    The dashboard is read-only against your Postgres mirror. Tracking, analyzing,
    and resetting never reach back to production.

## Run These Docs Locally

This site is [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/):

```bash
pip install mkdocs-material && mkdocs serve
```

It serves on [http://localhost:4000](http://localhost:4000) (pinned via `dev_addr`)
and live-reloads as you edit anything under `docs/`. `mkdocs build` writes a static
site to the gitignored `site/`.

## Next Steps

<div class="grid cards" markdown>

-   :material-monitor:{ .lg .middle } **[Using The Dashboard](guides/using-the-dashboard.md)**

    ---

    What the cards, columns, and drill-down actually show you.

-   :material-tune:{ .lg .middle } **[Configuration](guides/configuration.md)**

    ---

    Environment variables, accounts, and CLI flags.

</div>

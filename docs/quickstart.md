---
description: Install dependencies, configure production credentials, and run the API, daemon, and dashboard.
---

# Quickstart

This walks you through getting the dashboard running locally against a mirror of the
Reflecks production backend.

## Before You Start

!!! info
    You'll need **Python 3.12+** and **Node 18+**. The daemon also needs network
    access to the Reflecks production server and a real account on it.

## Install

1.  **Create a virtual environment and install the Python dependencies**

    ```bash
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    ```

    The API has no ML dependencies of its own; all the heavy lifting lives in the
    daemon. Everything installs together here, so you don't have to think about which
    process needs what.

2.  **Add your production credentials**

    ```bash
    cp .env.example .env.mirror
    ```

    Then fill in `PROD_USERNAME` and `PROD_PASSWORD` in `.env.mirror`.

    !!! note
        Only the daemon actually uses `.env.mirror`, and only to authenticate to
        production. The API and dashboard never call prod.

The SQLite database creates itself on first run, so there's nothing to migrate on a
fresh clone.

## Run

Three processes, one terminal each.

1.  **Start the read API**

    ```bash
    uvicorn app.main:app --port 8000 --reload
    ```

    This serves the materialized state at `http://localhost:8000`.

2.  **Start the ingestion and inference daemon**

    ```bash
    python -m app.pipeline
    ```

    !!! warning
        Run exactly one daemon. The cursor and idempotency logic assume a single
        writer, so a second daemon will fight the first.

3.  **Start the dashboard**

    ```bash
    cd frontend && npm install && npm run dev
    ```

    This opens the dashboard at `http://localhost:3000`.

!!! tip
    Prefer one command? `./scripts/start.sh` brings up all four processes (API,
    daemon started paused, dashboard, and these docs) in the background, and
    `./scripts/stop.sh` tears them down.

!!! note "Dev vs. production mode"
    By default `./scripts/start.sh` runs the dashboard in **dev mode** (the Vite
    dev server, with hot reload), which is what you want while editing the code.

    For a real **data-collection session**, run `./scripts/start.sh --prod`. It
    builds the dashboard and serves the static bundle instead. It's lighter, runs
    React effects once, and (unlike dev mode) a stray file save can't hot-reload
    the page and reset your open detail modal or a half-written note. Same API,
    daemon, database, and ports either way; only the dashboard build differs. The
    production build takes a few seconds, so the dashboard appears shortly after
    the URLs are printed.

## Track Your First Student

Open [http://localhost:3000](http://localhost:3000), type a student ID into **Track a
student**, and the daemon backfills their recent history, materializes their state,
and their card appears within a tick or two.

!!! success
    The dashboard is read-only against your local mirror. Tracking, analyzing, and
    resetting never reach back to production.

## Run These Docs Locally

This site is built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/),
installed in the same virtual environment.

```bash
mkdocs serve
```

It always serves on [http://localhost:4000](http://localhost:4000) (pinned via
`dev_addr` in `mkdocs.yml`), so it won't collide with the API on port 8000. The
preview live-reloads as you edit anything under `docs/`.

!!! note
    Cloned fresh and `mkdocs` isn't there? Install it into the venv with
    `pip install mkdocs-material`. For a one-off static build instead of the live
    preview, run `mkdocs build`; the output lands in `site/`, which is gitignored.

## Next Steps

<div class="grid cards" markdown>

-   :material-monitor:{ .lg .middle } **[Using The Dashboard](guides/using-the-dashboard.md)**

    ---

    What the cards, columns, and drill-down actually show you.

-   :material-tune:{ .lg .middle } **[Configuration](guides/configuration.md)**

    ---

    Every environment variable and CLI flag.

</div>

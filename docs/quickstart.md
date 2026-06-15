---
description: Install dependencies, configure production credentials, and run the API, daemon, and dashboard.
---

# Quickstart

Get the dashboard running locally against a mirror of the Reflecks production
backend.

## Prerequisites

!!! info
    Requires **Python 3.12+** and **Node 18+**. The daemon also needs network
    access to the Reflecks production server and a valid account on it.

## Install

1.  **Create a virtual environment and install Python dependencies**

    ```bash
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    ```

    The API has no ML dependencies; all the heavy compute lives in the daemon.
    Both are installed together here.

2.  **Configure production credentials**

    ```bash
    cp .env.example .env.mirror
    ```

    Then fill in `PROD_USERNAME` and `PROD_PASSWORD` in `.env.mirror`.

    !!! note
        `.env.mirror` is only needed by the **daemon**, to authenticate to the
        production server. The API and dashboard don't read it.

The SQLite database is created automatically on first run. There is nothing to
migrate on a fresh clone.

## Run

Three processes, each in its own terminal.

1.  **Start the read API**

    ```bash
    uvicorn app.main:app --port 8000 --reload
    ```

    Serves the materialized state at `http://localhost:8000`.

2.  **Start the ingestion + inference daemon**

    ```bash
    python -m app.pipeline
    ```

    !!! warning
        Run **exactly one** daemon instance. The cursor and idempotency logic
        assume a single writer. See [Operations](guides/operations.md).

3.  **Start the dashboard**

    ```bash
    cd frontend && npm install && npm run dev
    ```

    Opens the dashboard at `http://localhost:3000`.

## Track your first student

Open [http://localhost:3000](http://localhost:3000), type a student ID into
**Track a student**, and the daemon backfills their recent history, materializes
their state, and their card appears within a tick or two.

!!! success
    The dashboard is read-only against your local mirror. Tracking, analyzing,
    and resetting never touch production.

## Run these docs locally

This documentation site is built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/),
installed in the same virtual environment.

```bash
mkdocs serve
```

It always serves on [http://localhost:4000](http://localhost:4000) (pinned via
`dev_addr` in `mkdocs.yml`), so it never collides with the API on port 8000. The
preview live-reloads as you edit any file under `docs/`.

!!! note
    If you cloned fresh and `mkdocs` isn't found, install it into the venv with
    `pip install mkdocs-material`. To produce a static build instead of the live
    preview, run `mkdocs build` (output lands in `site/`, which is gitignored).

## Next steps

<div class="grid cards" markdown>

-   :material-monitor:{ .lg .middle } **[Using the dashboard](guides/using-the-dashboard.md)**

    ---

    What the cards, columns, and drill-down show.

-   :material-tune:{ .lg .middle } **[Configuration](guides/configuration.md)**

    ---

    Every environment variable and CLI flag.

</div>

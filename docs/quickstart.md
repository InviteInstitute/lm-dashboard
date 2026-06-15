---
description: Install dependencies, configure production credentials, and run the API, daemon, and dashboard.
---

# Quickstart

Let's get the dashboard running locally against a mirror of the Reflecks
production backend.

## Before you start

!!! info
    You'll need **Python 3.12+** and **Node 18+**. The daemon also needs network
    access to the Reflecks production server and a real account on it.

## Install

1.  **Make a virtual environment and install the Python deps**

    ```bash
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    ```

    The API itself has no ML dependencies; all the heavy lifting lives in the
    daemon. They install together here, so you don't have to think about it.

2.  **Add your production credentials**

    ```bash
    cp .env.example .env.mirror
    ```

    Then fill in `PROD_USERNAME` and `PROD_PASSWORD` in `.env.mirror`.

    !!! note
        Only the daemon reads `.env.mirror`, and only to authenticate to
        production. The API and dashboard never touch it.

The SQLite database creates itself on first run, so there's nothing to migrate on
a fresh clone.

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
        writer, so a second one will fight the first. There's more on this in
        [Operations](guides/operations.md).

3.  **Start the dashboard**

    ```bash
    cd frontend && npm install && npm run dev
    ```

    This opens the dashboard at `http://localhost:3000`.

## Track your first student

Open [http://localhost:3000](http://localhost:3000), type a student ID into **Track
a student**, and the daemon backfills their recent history, materializes their
state, and their card shows up within a tick or two.

!!! success
    The dashboard is read-only against your local mirror. Tracking, analyzing, and
    resetting never reach back to production.

## Run these docs locally

This documentation site is built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/),
installed in the same virtual environment.

```bash
mkdocs serve
```

It always serves on [http://localhost:4000](http://localhost:4000) (that's pinned
with `dev_addr` in `mkdocs.yml`), so it won't collide with the API on port 8000.
The preview live-reloads as you edit anything under `docs/`.

!!! note
    If you cloned fresh and `mkdocs` isn't there, install it into the venv with
    `pip install mkdocs-material`. For a static build instead of the live preview,
    run `mkdocs build` (the output lands in `site/`, which is gitignored).

## Next steps

<div class="grid cards" markdown>

-   :material-monitor:{ .lg .middle } **[Using the dashboard](guides/using-the-dashboard.md)**

    ---

    What the cards, columns, and drill-down actually show you.

-   :material-tune:{ .lg .middle } **[Configuration](guides/configuration.md)**

    ---

    Every environment variable and CLI flag.

</div>

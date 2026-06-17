# LM Dashboard

A live "who needs help" view for a room of students coding in VEX. It mirrors their
activity from the Reflecks production backend, infers each student's strategy with
an HMM, segments the session into episodes, and flags who needs attention
(wheel-spinning, idle, big rewrite) on one screen. Read-only against production.

```mermaid
flowchart LR
    students["Students coding<br/>in VEX"] --> prod[("Reflecks<br/>production server")]
    prod -. "polls, read-only" .-> daemon["Local daemon<br/>mirror and analyze"]
    daemon --> sqlite[("Local SQLite<br/>mirror")]
    sqlite --> api["Read API"]
    api --> dash["Researcher<br/>dashboard"]
```

> Full docs: run `mkdocs serve` and open http://localhost:4000, or read
> [`docs/DESIGN.md`](docs/DESIGN.md).

## Quick start

Python 3.12+ and Node 18+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env.mirror     # add PROD_USERNAME / PROD_PASSWORD
./scripts/start.sh              # API :8000, daemon (paused), dashboard :3000, docs :4000
```

Open http://localhost:3000, add a student ID, then click **Resume polling** for live
data. Stop everything with `./scripts/stop.sh`.

## What you get

- A card per student: strategy state (Iterator / Explorer / Stuck), strategy and
  episode sparklines, and **Present** / **Picked** toggles.
- A live **"who needs help"** column with **notes** you can jot per alert; click a
  learner for full detail and their complete notes log.
- Top bar: pause/resume polling, CSV **export** (one file per table in `exports/`),
  and reset.

## Under the hood

The daemon is the only writer; the API and dashboard only read a rebuildable SQLite
cache. Details live in [`docs/`](docs/): [Configuration](docs/guides/configuration.md),
[API](docs/reference/api.md), and [DESIGN](docs/DESIGN.md).

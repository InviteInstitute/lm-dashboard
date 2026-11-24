---
description: The Makefile command vocabulary, the ruff and prettier code style, and what CI checks on every pull request.
---

# Development

This repo and [vex-agent-integration](https://github.com/InviteInstitute/vex-agent-integration)
share one dev setup, so switching between them costs nothing. A **Makefile** gives both the
same command vocabulary, **ruff** and **prettier** own code style, and **GitHub Actions**
runs the same checks on every pull request.

## Set Up

You need Python 3.12, Node 20, and a local Postgres for the backend tests. Install the
backend (editable, with the dev extras) and the frontend dependencies in one step:

```bash
make install
```

That runs `pip install -e '.[dev]'` and `npm install` in `frontend/`. Run it inside an
activated virtualenv so `pytest` and `ruff` land on your `PATH`.

## The Makefile

`make` (or `make help`) lists every target. It is a thin wrapper over the compose files
and `scripts/`, so each target does exactly what running those by hand would.

| Target | What it does |
|---|---|
| `make dev` | start the local stack (API with reload, Vite on `:3000`), Ctrl-C to stop |
| `make down` | stop the local stack |
| `make logs` / `make ps` | follow logs / show stack status |
| `make test` | backend (pytest) and frontend (vitest) tests |
| `make lint` | ruff lint over the backend |
| `make format` | ruff (backend) and prettier (frontend), writing changes |
| `make format-check` | the same checks without writing, as CI runs them |
| `make build` | build the frontend bundle |
| `make deploy` | the guarded prod rollout |

!!! tip "Docker that needs sudo"
    The docker targets honor a `COMPOSE` variable. On a host where docker needs sudo,
    run e.g. `make dev COMPOSE='sudo docker compose'`.

!!! note "Deploy is complete on its own"
    `make deploy` runs `scripts/deploy.sh`, which rolls the stack. The frontend is built
    inside the Docker image, so there is no separate client build step.

## Code Style

**Ruff** is the single source of truth for Python linting and formatting. Its config
lives in `pyproject.toml` and is kept identical to vex-agent-integration. The rule set is
pyflakes, import sorting, pyupgrade, and bugbear. Line length is left to the formatter,
which the codebase favors dense over wrapped.

**Prettier** formats the frontend (JSX and CSS), configured in
`frontend/.prettierrc.json`, and an `.editorconfig` at the repo root keeps indentation and
line endings consistent across editors.

```bash
make format         # write changes
make format-check   # check only, the way CI does
```

!!! note "Blame stays readable"
    The one-time bulk reformats are recorded in `.git-blame-ignore-revs`. Point git at it
    so `git blame` skips them: `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

## Where Things Live

The backend is the `app/` package:

| Path | What it holds |
|---|---|
| `app/main.py` | the read API: every route, the board and ZANY gates, the static app |
| `app/goal_evidence.py` | shapes the goal engine's per-run profiles for the student sheet |
| `app/db.py` | all the SQL, the schema and the export, behind plain functions |
| `app/pipeline/` | the daemon: the Reflecks client, the poller, per-student workers, triggers |
| `app/zany.py` | reading ZANY's study logs from ATLAS-invite's store |
| `app/turnstile.py` | the Cloudflare Turnstile gate |
| `app/config.py`, `app/constants.py` | settings from the environment, and the tunable numbers |

The dashboard is `frontend/src/`. `CohortDashboard.jsx` holds the board's state and
actions and wires everything else together:

| Path | What it holds |
|---|---|
| `components/` | the header, the student board and cards, the alert feed, toasts, the modals, the activity strips |
| `components/sheet/` | the student sheet: its header, program, notes and trigger history |
| `components/goals/` | goal evidence: the run table, goal rows, the battery and their marks |
| `hooks/` | the live data (stream and polling), the open student's detail, safe writes with the outbox, the ZANY source, the theme |
| `lib/` | time formatting, a student's status, the download helper |
| `styles/` | `carbon.scss` and the INVITE theme, then one stylesheet per area, loaded in order by `main.jsx` |
| `constants.js` | the colours of runs, episodes and triggers, and the few timing numbers |

## Tests

`make test` runs both suites. The backend suite needs a Postgres it can reach and builds
its own schema, so there is no migration step. See [Running the tests](testing.md) for the
full walkthrough, coverage, and what each side covers.

## Continuous Integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request, in two
jobs that mirror the make targets:

- **backend** - installs the package, runs `ruff check` and `ruff format --check` over
  `app`, `tests` and `scripts`, then runs pytest against a throwaway Postgres (the suite
  creates its own schema).
- **frontend** - runs the prettier check, the vitest suite, and a production build.

A green run means lint, formatting, both test suites, and the frontend build are all intact.

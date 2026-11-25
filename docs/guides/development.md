---
description: Setup, the make targets, code style, where the code lives, CI, deploys and how the docs keep up.
---

# Development

This repo and [vex-agent-integration](https://github.com/InviteInstitute/vex-agent-integration)
share one setup. A Makefile gives both the same commands, ruff and prettier own the code style, and
GitHub Actions runs the same checks on every pull request.

## Set Up

You need Python 3.12, Node 20 and a Postgres you can reach for the backend tests. Clone with the
submodule, since the learner-model engine lives in `vendor/agent-lm-packages`.

```bash
git clone --recurse-submodules https://github.com/InviteInstitute/lm-dashboard
cd lm-dashboard
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ./vendor/agent-lm-packages
make install
```

`make install` runs `pip install -e '.[dev]'` and `npm install` in `frontend/`. Run it inside the
virtualenv so `pytest` and `ruff` end up on your `PATH`.

## The Makefile

`make` (or `make help`) lists every target. Each one is a thin wrapper over the compose files and
`scripts/`, so it does what running those by hand would do.

| Target | What it does |
|---|---|
| `make dev` | start the local stack (API with reload, Vite on `:3000`). Ctrl-C stops it |
| `make down` | stop the local stack |
| `make logs`, `make ps` | follow the logs, show what is running |
| `make test` | the backend (pytest) and frontend (vitest) tests |
| `make lint` | ruff over the backend |
| `make format` | ruff on the backend and prettier on the frontend, writing changes |
| `make format-check` | the same checks without writing, the way CI runs them |
| `make build` | build the frontend bundle |
| `make deploy` | the guarded rollout on a server (see [Deploying](#deploying)) |

!!! tip "Docker that needs sudo"
    The docker targets read a `COMPOSE` variable. On a host where docker needs sudo, run
    `make dev COMPOSE='sudo docker compose'`.

## Code Style

Ruff lints and formats the Python. Its config is in `pyproject.toml`, the same as in
vex-agent-integration. The rules are pyflakes, import sorting, pyupgrade and bugbear. Line length
is left to the formatter.

Prettier formats the frontend (JSX and CSS), with its config in `frontend/.prettierrc.json`. An
`.editorconfig` at the root keeps indentation and line endings the same across editors.

```bash
make format         # write changes
make format-check   # only check, like CI
```

!!! note "Keep blame readable"
    The one-time bulk reformats are listed in `.git-blame-ignore-revs`. Run
    `git config blame.ignoreRevsFile .git-blame-ignore-revs` once, and `git blame` skips them.

## Where Things Live

The backend is the `app/` package.

| Path | What it holds |
|---|---|
| `app/main.py` | the API, with every route, the board and ZANY gates, and the static app |
| `app/db.py` | all the SQL, the schema and the export, behind plain functions |
| `app/pipeline/` | the daemon, with the Reflecks client, the pollers, the per-student workers and the inactive sweep |
| `app/zany.py` | reading ZANY's study logs from ATLAS-invite's store, and the research login |
| `app/goal_evidence.py` | shapes the goal engine's per-run profiles for the student sheet |
| `app/turnstile.py` | the Cloudflare Turnstile gate |
| `app/config.py`, `app/constants.py` | settings from the environment, and the numbers you can tune |
| `scripts/` | `deploy.sh`, `export_csv.py` for a CSV dump from the terminal, `follow_logs.py`, and `docs_sync.py` for the docs |
| `vendor/agent-lm-packages` | the engine, as a git submodule: `learner_models` (edit distance, triggers, episodes), `goal_strategy` (goal evidence) and `log_parser_delta_engine` (the readable program and the prompt) |

The dashboard is `frontend/src/`. `CohortDashboard.jsx` holds the board's state and actions and
wires the rest together.

| Path | What it holds |
|---|---|
| `components/` | the header, the board and its cards, the alert feed, toasts, dialogs and the activity tracks |
| `components/sheet/` | the student sheet, with its header, program, notes and trigger history |
| `components/goals/` | goal evidence, with the run table, goal rows, the battery and their marks |
| `hooks/` | the live data (stream and polling), the open student's detail, safe writes with the outbox, the board's source and the theme |
| `lib/` | time formatting, a student's status and the download helper |
| `styles/` | `carbon.scss` and the INVITE theme, then one stylesheet per area, loaded in order by `main.jsx` |
| `constants.js` | the colors of runs, episodes and triggers, and the few timing numbers |

## Tests

`make test` runs both suites. The backend suite needs a Postgres it can reach and builds its own
schema. [Running the tests](testing.md) has the details.

## Continuous Integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request, in two jobs that
match the make targets.

- The backend job installs the engine and the package, runs `ruff check` and `ruff format --check`
  on `app`, `tests` and `scripts`, then runs pytest against a throwaway Postgres.
- The frontend job runs the prettier check, the vitest suite and a production build.

A green run means lint, formatting, both test suites and the frontend build all pass.

## Deploying

On the INVITE server, the live checkout is `/var/www/lm-dashboard` on `main`. A push to `main`
makes GitHub call the server's webhook, which runs `/usr/local/bin/lm-dashboard-deploy.sh` as the
`ubuntu` user. That script runs `make deploy`, which runs `scripts/deploy.sh`.

`scripts/deploy.sh` refuses to run over uncommitted changes, pulls with `--ff-only`, updates the
submodule, builds the image, recreates the `api` and `daemon` containers and waits for `/healthz` to
answer 200. The database keeps running the whole time. The frontend is built inside the image, so
there is no separate build step.

A pull that only changes `docs/`, `README.md`, `zensical.toml` or `.github/` leaves the stack running.
Rolling it would restart the daemon, which starts a new session and empties every card, and the
image doesn't hold the docs anyway.

So shipping a change means merging a pull request into `main`. Don't run `docker compose up` on the
server by hand.

## The Docs

The docs are the pages in `docs/`, with their nav in `zensical.toml`. They are published as the
Learner Modeling Dashboard section of [docs.inviteai.org](https://docs.inviteai.org/lm-dashboard/),
which also holds the ZANY and ATLAS docs. That site's theme, home page and build live in
InviteInstitute/docs, and the INVITE server rebuilds it within two minutes of a change here.
`.github/workflows/docs.yml` keeps the pages up to date on every push to `main`.

1.  `scripts/docs_sync.py` sends glm-5.3 on NCSA's Lumen the diff of the push, the code and the
    current docs. Its instructions are the writing rules and skills from
    [Maharsh17/claude-config](https://github.com/Maharsh17/claude-config), read fresh on each run,
    so a change to those rules reaches the docs on the next push. A push that only changes the
    docs skips the call.
2.  The model returns only the pages that the change made wrong or incomplete. The script writes
    them, and `zensical build --strict` checks that every link and page still holds.
3.  If any page changed, the job commits it to `main`. That commit, by `github-actions[bot]`, is the
    record of what the bot wrote, and docs.inviteai.org shows it a few minutes later.

The job needs the repository secret `LUMEN_API_KEY`. The workflow runs one push at a time, so two
quick pushes never race to commit the docs. A push the bot makes starts no workflow, so it never
runs on its own commit, and the server's deploy skips a docs-only commit (see
[Deploying](#deploying)).

The settings at the top of `scripts/docs_sync.py` say which pages the bot may write. A path that
normalizes to a different file, like `docs//changes/x.md` or `../x`, is refused, and so is an
absolute path, because either could slip past the protected list. zany and atlas-invite run
copies of the same script with their own settings. To try it on your machine, set `LUMEN_API_KEY`
and run the script. It compares `--head` (default `HEAD`) with `--base` (default the commit
before it) and only edits files in your checkout, so review them with `git diff`.

```bash
python scripts/docs_sync.py --style ../claude-config
```

Edit the docs by hand whenever you like. The bot works from what is on `main`, so it keeps your
changes and only fixes what the code made wrong.

---
description: Run the whole stack (Postgres, the API and the daemon) with one docker compose command.
---

# Quickstart

One compose file runs the whole stack. That is Postgres, the API (which also serves the dashboard)
and the ingestion daemon. It is the same file on your laptop and on the server.

## Before You Start

You need Docker. On macOS and Windows that is Docker Desktop. On Linux it is Docker with the
Compose v2 plugin. The daemon also needs network access to the Reflecks production server and an
account on it.

## Configure

Make two small files. Git ignores both.

1.  Copy the example for the app's secrets and fill it in.

    ```bash
    cp .env.example .env.mirror
    ```

    `PROD_USERNAME` and `PROD_PASSWORD` are the daemon's Reflecks login. `SESSION_SECRET` signs the
    API's cookies, and `TURNSTILE_SECRET` is the Cloudflare Turnstile secret key.
    [Configuration](guides/configuration.md) lists every setting.

2.  Pick a database password for compose.

    ```bash
    echo "POSTGRES_PASSWORD=$(python3 -c 'import secrets;print(secrets.token_hex(16))')" > .env
    ```

You don't set `DATABASE_URL` yourself, because compose builds it from that password. The API
creates the schema when it starts, so there is no migration step either.

## Run

```bash
make dev      # the same as: docker compose up
```

In development, compose also loads `compose.override.yml`. That runs the dashboard under Vite with
hot reload at [http://localhost:3000](http://localhost:3000), which sends `/api` on to the API. It
also mounts `app/` into the API and daemon containers. The API runs with `--reload` and restarts
when you change the code. The daemon picks up a change when you run `docker compose restart daemon`.
It also turns off the dead-man's switch, so a local board is polled as soon as it has students.

On a server, only the base file runs, and the API serves the built dashboard on
`127.0.0.1:8000`. Put nginx or another reverse proxy in front of it for TLS.
[Development](guides/development.md#deploying) shows how the INVITE server deploys it.

!!! warning "Run exactly one daemon"
    The ingest cursor and the duplicate check assume one writer. Compose starts one, so don't
    start a second by hand.

A few commands you will use often.

```bash
docker compose ps                  # what is running
docker compose logs -f daemon      # follow one service (api, daemon or db)
docker compose down                # stop everything
```

## Track Your First Student

Open the dashboard. The first time, the browser passes a Turnstile check, and it remembers that for
12 hours. Type a student ID into **Track student IDs** beside the Students heading. The daemon
copies the student's activity since it started, works out their state, and their card appears
within a second or two.

!!! note "Each browser is its own board"
    The board ID lives in the browser's local storage. Clearing the site's data starts a new,
    empty board.

## Read These Docs Locally

The docs are published at [docs.inviteai.org](https://docs.inviteai.org/lm-dashboard/). To preview
them here, with [Zensical](https://zensical.org) and the nav in `zensical.toml`, run this.

```bash
pip install zensical
zensical serve
```

They serve on [http://localhost:4000](http://localhost:4000) and reload as you edit anything in
`docs/`. `zensical build --strict` writes the static site to `site/`, which git ignores, and
fails on a broken link or anchor.

## Next Steps

<div class="grid cards" markdown>

-   :material-monitor:{ .lg .middle } **[Using The Dashboard](guides/using-the-dashboard.md)**

    ---

    What the cards, the alert column and the student sheet show you.

-   :material-tune:{ .lg .middle } **[Configuration](guides/configuration.md)**

    ---

    Environment variables and daemon flags.

-   :material-wrench:{ .lg .middle } **[Development](guides/development.md)**

    ---

    The make targets, code style, CI and deploys.

</div>

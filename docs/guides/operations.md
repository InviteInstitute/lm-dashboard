---
description: Single-writer rule, crash safety, failure modes, and migrating an existing Reflecks database.
---

# Operations

A few things worth knowing for running this day to day.

## One writer, always

!!! warning
    Run exactly one daemon. The cursor and idempotency logic assume a single
    writer, so two daemons will race the cursor, and that's the one thing that
    genuinely breaks the system.

The API can have as many read workers as you want. It's only the daemon that has to
be a singleton.

## Crash safety

A persisted cursor plus unique event IDs make a restart lossless. When the daemon
comes back, it re-drains a small overlap window and de-dupes, and the in-memory
worker state rebuilds itself from the raw logs.

## Everything rebuilds

The derived tables are just a cache of the raw logs. Delete them, or hit
[Reset](using-the-dashboard.md#reset), and they replay from `vex_log`.

## Failure modes

| What happens | How it behaves |
|---|---|
| Crash mid-drain | re-fetches the overlap on restart and de-dupes, so nothing is lost |
| Prod down or 5xx | failure backoff kicks in, logs `UNHEALTHY`, resumes when prod is back |
| Daemon restart | workers rehydrate from `vex_log`, cursor was persisted |
| Two daemons by mistake | the cursor races; this is the one thing that breaks, so run exactly one |

## Migrating an old Reflecks database

You only need this if you're bringing over an old `reflecks` SQLite file. A fresh
clone doesn't need it. The migration renames the legacy `rabbitmq_*` tables to the
clean names and reclaims the space they were sitting on.

1.  **Back up the database first**

    ```bash
    cp db.sqlite3 db.backup.sqlite3
    ```

2.  **Run the migration**

    ```bash
    python scripts/migrate_db.py
    ```

    It renames the tables in place and vacuums the file, reclaiming the big block of
    free pages an old Reflecks database tends to carry.

## Exporting data

Use the **Export** button on the dashboard, or run the standalone script, to dump
the current tables to CSV. Either way it's non-destructive and safe to run any time.

```bash
python scripts/export_csv.py
```

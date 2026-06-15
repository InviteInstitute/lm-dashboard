---
description: Single-writer rule, crash safety, failure modes, and migrating an existing Reflecks database.
---

# Operations

Notes for running the system day to day.

## Single writer

!!! warning
    Run **exactly one** daemon instance. The cursor and idempotency logic assume
    a sole writer. Two daemons race the cursor, which is the one thing that
    breaks the system.

The API can have multiple read workers; only the daemon must be a singleton.

## Crash safety

A persisted cursor plus unique event IDs make a restart lossless. On restart the
daemon re-drains a small overlap window and de-dupes. In-memory worker state is
rebuilt from the raw logs.

## Fully rebuildable

The derived tables are a cache of the raw logs. Delete them (or hit
[Reset](using-the-dashboard.md#reset)) and they replay from `vex_log`.

## Failure modes

| Failure | Behavior |
|---|---|
| Crash mid-drain | re-fetch overlap on restart, dedupe → lossless |
| Prod down / 5xx | failure backoff, `UNHEALTHY` log, resumes when back |
| Daemon restart | workers rehydrate from `vex_log`; cursor persisted |
| Two daemons (mistake) | cursor races — **the one thing that breaks**; run exactly one |

## Migrating an existing Reflecks database

Only needed if you are bringing over an old `reflecks` SQLite file; not required
for a fresh clone. The migration renames the legacy `rabbitmq_*` tables to the
clean names and reclaims space.

1.  **Back up the database first**

    ```bash
    cp db.sqlite3 db.backup.sqlite3
    ```

2.  **Run the migration**

    ```bash
    python scripts/migrate_db.py
    ```

    This renames tables in place and vacuums the file, reclaiming the large block
    of free pages an old Reflecks database carries.

## Exporting data

Use the **Export** button on the dashboard, or run the standalone script, to dump
the current tables to CSV. Export is non-destructive and safe to run any time.

```bash
python scripts/export_csv.py
```

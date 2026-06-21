---
description: Single-writer rule, crash safety, failure modes, and migrating an existing Reflecks database.
---

# Operations

A few things worth knowing for running this day to day.

## One Writer, Always

!!! warning
    Run exactly one daemon. The cursor and idempotency logic assume a single writer,
    so two daemons will race the cursor, and that's the one thing that genuinely
    breaks the system.

The API can have as many read workers as you want. It's only the daemon that has to be
a singleton.

## Crash Safety

A persisted cursor plus unique event IDs make a restart lossless. When the daemon
comes back, it re-drains a small overlap window and de-dupes, and the in-memory worker
state rebuilds itself from the raw logs.

## Everything Rebuilds

The derived tables are just a cache of the raw logs. Delete them, or hit
[Reset](using-the-dashboard.md#reset), and they replay from `vex_log`.

## Failure Modes

| What Happens | How It Behaves |
|---|---|
| Crash mid-drain | re-fetches the overlap on restart and de-dupes, so nothing is lost |
| Prod down or 5xx | failure backoff kicks in, logs `UNHEALTHY`, resumes when prod is back |
| Daemon restart | workers rehydrate from `vex_log`, cursor was persisted |
| Two daemons by mistake | the cursor races; this is the one thing that breaks, so run exactly one |

## Exporting Data

Use the **Export** button on the dashboard, or run the standalone script, to dump the
current tables to CSV. Either way it's non-destructive and safe to run any time.

```bash
python scripts/export_csv.py
```

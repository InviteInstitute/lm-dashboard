---
description: How the FastAPI read API serves the materialized view and how the React dashboard renders it.
---

# Read path and dashboard

The read side is deliberately thin. It serves the state the daemon already
computed and does no machine learning of its own.

## The API

The API is a FastAPI app (`uvicorn app.main:app`).

- Opens a fresh SQLite connection per request, reads the **materialized view**,
  and shapes it into the dashboard's payload.
- Has **no ML imports**. All the expensive HMM and episode work already ran on
  the write side.
- Ensures the schema exists on load, so a fresh clone works regardless of whether
  the API or the daemon starts first.

Beyond reads, the API performs only tiny writes: adding or removing tracked
students, acknowledging triggers, and signaling a reset. See the
[API reference](../reference/api.md) for every endpoint.

## The dashboard

The React dashboard polls two endpoints in parallel, each on a ~1.5s timer:

<div class="grid cards" markdown>

-   :material-view-grid:{ .lg .middle } **`/api/student_states/`**

    ---

    Drives the **student card grid**. One box per tracked student, ordered by
    `studentID` so a card never jumps when its own data updates. The detail
    modal reuses the same payload, so a drill-down needs no extra request.

-   :material-hand-back-right:{ .lg .middle } **`/api/triggers/`**

    ---

    Drives the **who-needs-help column**. Every open and recently-resolved
    intervention flag — wheel-spin, inactive, and big-rewrite — colour-coded
    and individually acknowledgeable.

</div>

The roster (`/api/tracked/`) is polled on the same timer so adding or removing a
student reflects immediately and so the alert column can hide alerts for
students that are no longer tracked.

## Why the dashboard is fast

The dashboard reads a **precomputed materialized view**: small, indexed rows. It
still hits SQLite on every request; it is fast because *what* it reads is cheap,
not because of the in-memory workers.

!!! note
    The in-memory workers speed up the **daemon**, not the dashboard. The
    dashboard's speed comes entirely from reading a cheap, already-computed
    projection.

## Payload shape

Each student in `/api/student_states/` carries the full derived state:

| Field | Meaning |
|---|---|
| `current_state` / `current_label` | latest HMM state (0/1/2) and its label |
| `stuck` / `consecutive_stuck` | wheel-spin flag and how long it has held |
| `run_count` / `event_count` | activity counters |
| `last_seen` | timestamp of the most recent event |
| `state_sequence` | per-run HMM states (the strategy sparkline) |
| `hmm` | full HMM blob: runs, observation labels, run count |
| `episodes` | segmented episodes, pauses, and events |
| `block` | the current "playground" LLM prompt and its timestamp |

See [Using the dashboard](../guides/using-the-dashboard.md) for how these render.

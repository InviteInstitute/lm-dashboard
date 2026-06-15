---
description: Every endpoint the FastAPI read API exposes, with request and response shapes.
---

# API reference

The read API runs at `http://localhost:8000`. It serves the materialized state
the daemon computes and performs only small writes (track, ack, reset, export).
There is no authentication; the endpoints are local-only.

## Endpoints at a glance

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/` | health check |
| `GET`  | `/api/student_states/` | materialized per-student state (the dashboard's main read) |
| `GET`  | `/api/tracked/` | the tracked-student roster |
| `POST` | `/api/tracked/` | track or untrack a student |
| `GET`  | `/api/triggers/` | active + recently-resolved intervention feed |
| `POST` | `/api/triggers/ack/` | dismiss a trigger |
| `POST` | `/api/export/` | write a CSV snapshot of all current data |
| `POST` | `/api/reset/` | clear all local progress and flags + signal the daemon |
| `GET`  | `/api/polling/` | whether the daemon is currently polling production |
| `POST` | `/api/polling/` | pause or resume the daemon's production polling |

---

## GET /

Health check.

```json title="Response"
{ "service": "luc-dashboard", "ok": true }
```

---

## GET /api/student_states/

The dashboard's main read: the materialized per-student state.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `students` | string | comma-separated student IDs to filter to (`?students=a,b`) |
| `classCode` | string | filter to a single class code |

```json title="Response"
{
  "students": [
    {
      "studentID": "...",
      "classCode": "...",
      "current_state": 2,
      "current_label": "stuck",
      "stuck": true,
      "consecutive_stuck": 3,
      "run_count": 12,
      "event_count": 240,
      "last_seen": "2026-06-14T10:31:00",
      "state_sequence": [0, 1, 1, 2, 2],
      "hmm": { "runs": [], "obs_labels": [], "run_count": 12 },
      "episodes": { "events": [], "episodes": [], "pauses": [] },
      "block": { "llm_prompt": "...", "timestamp": "2026-06-14T10:31:00" },
      "updated_at": "2026-06-14T10:31:01"
    }
  ],
  "student_count": 1,
  "stuck_count": 1,
  "stuck_state": 2,
  "state_labels": { "0": "iterator", "1": "explorer", "2": "stuck" }
}
```

!!! note
    Rows are sorted with stuck students first, then by most recent activity. A
    request for more than 500 student IDs returns `400`.

---

## GET /api/tracked/

The tracked-student roster.

```json title="Response"
{ "tracked": [ { "studentID": "...", "backfilled": true, "has_data": true } ], "count": 1 }
```

---

## POST /api/tracked/

Add or remove a tracked student. Adding triggers a one-time backfill by the
daemon.

```json title="Track a student"
{ "studentID": "abc123" }
```

```json title="Untrack and delete local data"
{ "studentID": "abc123", "remove": true }
```

Responses are `{ "added": "abc123" }` or `{ "removed": "abc123" }`. A missing
`studentID` returns `400`.

---

## GET /api/triggers/

The intervention feed: active triggers plus ones resolved in the last 120
seconds, newest first, unacknowledged only.

```json title="Response"
{
  "triggers": [
    {
      "id": 42,
      "studentID": "...",
      "trigger_type": "wheel_spin",
      "label": "...",
      "value": null,
      "started_at": "2026-06-14T10:25:00",
      "resolved_at": null,
      "active": true,
      "age_seconds": 360.0
    }
  ],
  "active_count": 1,
  "counts": { "wheel_spin": 1 }
}
```

The three trigger types are `wheel_spin` (HMM stuck state), `inactive` (≥ 5 min
idle), and `big_change` (change-score ≥ 0.5).

---

## POST /api/triggers/ack/

Dismiss a trigger by `id`, or all open triggers for a student.

```json title="By id"
{ "id": 42 }
```

```json title="By student"
{ "studentID": "abc123" }
```

Returns `{ "acknowledged": n }`. Providing neither returns `400`.

---

## POST /api/export/

Write a CSV snapshot of all current data to `exports/export_<timestamp>/`. This
is **read-only**; it never modifies the database.

```json title="Response"
{
  "exported": true,
  "at": "2026-06-14T10:31:00",
  "dir": "/.../exports/export_2026-06-14_103100",
  "rows": { "vex_log": 259, "student_state": 2 }
}
```

---

## POST /api/reset/

Clear all local student data (logs, episodes, HMM state, flags) and tell the
daemon to drop its in-memory workers. Students stay tracked; the board rebuilds
from new activity.

!!! warning
    This has **no backup**. Call [`/api/export/`](#post-apiexport) first if you
    want a CSV copy. Local only; production is untouched.

```json title="Response"
{ "reset": true, "at": "2026-06-14T10:31:00" }
```

---

## GET /api/polling/

Whether the daemon is currently polling production. Defaults to enabled.

```json title="Response"
{ "enabled": true }
```

---

## POST /api/polling/

Pause or resume the daemon's production polling. When paused, the daemon makes
**zero requests to prod** — it keeps running locally and resumes within ~1 second
of being re-enabled. Use it to stop loading production between sessions without
killing the process.

```json title="Pause"
{ "enabled": false }
```

```json title="Resume"
{ "enabled": true }
```

Returns the new state, e.g. `{ "enabled": false }`. This is a local control flag
(stored in `meta`); production is untouched.

---
description: Every endpoint the FastAPI read API exposes, with request and response shapes.
---

# API Reference

The read API runs at `http://localhost:8000`. It serves the materialized state the
daemon computes and performs only small writes (track, ack, notes, toggles, reset,
export, polling). There is no authentication; the endpoints are local-only.

## Endpoints At A Glance

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/` | health check |
| `GET`  | `/api/student_states/` | materialized per-student state (the dashboard's main read) |
| `GET`  | `/api/student_states/{id}/` | the heavy single-student payload (incl. the playground prompt) |
| `GET`  | `/api/tracked/` | the tracked-student roster |
| `POST` | `/api/tracked/` | track or untrack a student |
| `GET`  | `/api/triggers/` | active + recently-resolved intervention feed |
| `POST` | `/api/triggers/ack/` | dismiss a trigger |
| `GET`  | `/api/triggers/config/` | which trigger types are enabled |
| `POST` | `/api/triggers/config/` | enable or disable a trigger type |
| `POST` | `/api/presence/` | toggle whether a student is present in the room |
| `POST` | `/api/picked/` | toggle whether a student has been picked/interviewed |
| `GET`  | `/api/notes/` | a student's notes |
| `POST` | `/api/notes/` | add a note |
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
      "hmm": { "runs": [], "obs_labels": {}, "run_count": 12 },
      "episodes": { "events": [], "episodes": [], "pauses": [] },
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
    Rows are sorted with stuck students first, then by most recent activity. This
    list is the *light* shape: it omits the bulky playground `block`, which you get
    from the single-student endpoint below. A request for more than 500 student IDs
    returns `400`.

---

## GET /api/student_states/{id}/

The heavy payload for one student. Same fields as a row above, plus the playground
`block`:

```json title="Response (extra field)"
{
  "block": { "llm_prompt": "...", "timestamp": "2026-06-14T10:31:00" }
}
```

Returns `404` when the student is tracked but has no materialized state yet.

---

## GET /api/tracked/

The tracked-student roster.

```json title="Response"
{
  "tracked": [
    {
      "studentID": "...",
      "backfilled": true,
      "has_data": true,
      "present": true,
      "picked": false,
      "picked_at": null
    }
  ],
  "count": 1
}
```

---

## POST /api/tracked/

Add or remove a tracked student. Adding triggers a one-time backfill by the daemon.

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

The intervention feed: active triggers plus ones resolved in the last 120 seconds,
newest first, unacknowledged only.

```json title="Response"
{
  "triggers": [
    {
      "id": 42,
      "studentID": "...",
      "trigger_type": "wheel_spin",
      "label": "Wheel-spinning",
      "value": "3 re-runs",
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

The three trigger types are `wheel_spin` (HMM stuck state), `inactive` (≥ 5 min idle),
and `big_change` (change-score ≥ 0.5).

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

## GET /api/triggers/config/

Which trigger types are currently enabled (all on by default), with their labels.

```json title="Response"
{
  "enabled": { "wheel_spin": true, "inactive": true, "big_change": true },
  "labels": { "wheel_spin": "Wheel-spinning", "inactive": "Inactive", "big_change": "Big rewrite" }
}
```

---

## POST /api/triggers/config/

Enable or disable a trigger type. Disabling it makes the daemon stop firing that type
and resolve its open alerts on the next tick.

```json title="Request"
{ "trigger_type": "inactive", "enabled": false }
```

Returns the full `enabled` map. An unknown `trigger_type` returns `400`.

---

## POST /api/presence/

Toggle whether a tracked student is present in the room. Stored on `tracked_student`,
so it's included in the CSV export.

```json title="Request"
{ "studentID": "abc123", "present": false }
```

Returns `{ "studentID": "abc123", "present": false }`. A missing `studentID`
returns `400`.

---

## POST /api/picked/

Toggle whether a tracked student has been picked/interviewed this session. Stored on
`tracked_student` (with `picked_at`) and logged to `pick_event`.

```json title="Request"
{ "studentID": "abc123", "picked": true }
```

Returns `{ "studentID": "abc123", "picked": true }`. A missing `studentID`
returns `400`.

---

## GET /api/notes/

A student's notes, oldest first.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `studentID` | string | required; the student to list notes for |

```json title="Response"
{ "notes": [ { "id": 1, "studentID": "...", "ts": "...", "text": "...", "trigger_id": null, "trigger_type": null, "created_at": "..." } ], "count": 1 }
```

A missing `studentID` returns `400`.

---

## POST /api/notes/

Add a note for a learner. Include `trigger_id` / `trigger_type` to link it to the
alert it was written from; omit both for a free-standing note.

```json title="Request"
{ "studentID": "abc123", "text": "talked through the loop", "trigger_id": 42, "trigger_type": "wheel_spin" }
```

Returns the created note row. A missing `studentID` or empty `text` returns `400`.

---

## POST /api/export/

Write a CSV snapshot of all current data to `exports/export_<timestamp>/`. This is
**read-only**; it never modifies the database.

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

Clear all local student data (logs, episodes, HMM state, flags) and the researcher
notes, and tell the daemon to drop its in-memory workers. Students stay tracked; the
board rebuilds from new activity.

!!! info
    A CSV backup (notes included) is written to `exports/reset_<timestamp>/` before
    anything is cleared, so nothing is lost. Local only; production is untouched.

```json title="Response"
{
  "reset": true,
  "at": "2026-06-14T10:31:00",
  "backup": "/.../exports/reset_2026-06-14_103100"
}
```

---

## GET /api/polling/

Whether the daemon is currently polling production. Defaults to enabled.

```json title="Response"
{ "enabled": true }
```

---

## POST /api/polling/

Pause or resume the daemon's production polling. When it's paused, the daemon makes
zero requests to prod. It keeps running locally and picks back up within about a
second of being re-enabled. This is how you stop loading production between sessions
without killing the process.

```json title="Pause"
{ "enabled": false }
```

```json title="Resume"
{ "enabled": true }
```

Returns the new state, e.g. `{ "enabled": false }`. This is a local control flag
(stored in `meta`); production is untouched.

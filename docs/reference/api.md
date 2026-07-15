---
description: Every endpoint the FastAPI read API exposes, with request and response shapes.
---

# API Reference

The read API runs at `http://localhost:8000`. It serves the materialized state the
daemon computes and performs only small writes (track, ack, notes, toggles, reset,
export, polling).

By default the endpoints are open (local-only). When served remotely, an origin-wide
HTTP Basic Auth gate is turned on (see [Configuration](../guides/configuration.md));
it applies to every route below, including the static dashboard. In remote builds the
API also serves the built React app at `/`, so the paths below live under `/api`.

## Endpoints At A Glance

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/healthz` | health check |
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
| `POST` | `/api/export/` | download a zip of CSV snapshots of all current data |
| `POST` | `/api/reset/` | clear all local progress and flags + signal the daemon |
| `GET`  | `/api/polling/` | whether the daemon is currently polling production |
| `POST` | `/api/polling/` | pause or resume the daemon's production polling |

---

## GET /healthz

Liveness check. It's at `/healthz` rather than `/` so the static dashboard can be
served from the root in remote builds.

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
      "run_count": 12,
      "event_count": 240,
      "last_seen": "2026-06-14T10:31:00",
      "runs": {
        "runs": [
          { "index": 0, "edit_distance": null, "ts": "2026-06-14T10:20:00" },
          { "index": 1, "edit_distance": 0, "ts": "2026-06-14T10:22:00" },
          { "index": 2, "edit_distance": 7, "ts": "2026-06-14T10:25:00" }
        ],
        "run_count": 12
      },
      "episodes": { "events": [], "episodes": [], "pauses": [] },
      "updated_at": "2026-06-14T10:31:01"
    }
  ],
  "student_count": 1
}
```

!!! note
    Rows are sorted by most recent activity. Each run's `edit_distance` is the integer
    APTED tree-edit-distance from the previous run (`null` for the first run); that
    sequence is what the dashboard colours and what every trigger reads. There is no
    stored status field, the dashboard derives a student's headline state from the
    triggers feed. This is the *light* shape: it omits the bulky playground `block`,
    which you get from the single-student endpoint below. A request for more than 500
    student IDs returns `400`.

!!! note "Viewer heartbeat"
    A `GET` here also stamps `meta.viewer_last_seen`. Because the dashboard polls this
    on a timer (and stops when its tab is hidden), a fresh stamp means a dashboard is
    open, which is what the daemon's dead-man's switch reads. See
    [Configuration](../guides/configuration.md#the-dead-mans-switch).

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
      "value": "6 identical reruns",
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

There are five trigger types, all defined on the per-run `edit_distance`:

| `trigger_type` | Label | Fires when | Example `value` |
|---|---|---|---|
| `wheel_spin` | Wheel-spinning | 6+ consecutive `edit_distance == 0` | `6 identical reruns` |
| `resilience` | Resilience | an edit after 4+ zeros | `recovered after 5 reruns` |
| `inactive` | Inactive | idle >= 240s (4 min) | `idle 7m` |
| `explorer` | Explorer | a run with `edit_distance >= 13` | `changed 21` |
| `iterative` | Step-by-Step | 6 runs with `edit_distance >= 1` | `6 steady edits` |

`wheel_spin`, `resilience`, `explorer`, and `iterative` are momentary (one row per
qualifying run); `inactive` is sustained (open while idle, re-alerts after 10 min if
acked and still holding).

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
  "enabled": { "wheel_spin": true, "resilience": true, "inactive": true, "explorer": true, "iterative": true },
  "labels": {
    "wheel_spin": "Wheel-spinning", "resilience": "Resilience", "inactive": "Inactive",
    "explorer": "Explorer", "iterative": "Step-by-Step"
  }
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

Download a **zip of CSV snapshots** of all current data (one CSV per table: raw
events, materialized state, triggers, roster, notes). The zip is built entirely in
memory and streamed to the browser, so nothing is written to disk and the database is
never touched. This is **read-only** and safe to run any time.

```http title="Response"
200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename="lm-dashboard_export_2026-06-14_103100.zip"

<binary zip: student_state.csv, trigger_event.csv, vex_log.csv, ...>
```

---

## POST /api/reset/

Clear all local student data (logs, episodes, run/trigger state, flags) and the
researcher notes, and tell the daemon to drop its in-memory workers. Students stay
tracked; the board rebuilds from new activity.

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

!!! note
    This is the *manual* pause. When the daemon runs with `--require-viewer` (remote
    serving arms it automatically), there's also an *automatic* pause: prod polling
    stops whenever no dashboard has polled recently. The two are independent, the
    daemon polls only when it's manually enabled **and** a viewer is present. See
    [Configuration](../guides/configuration.md#the-dead-mans-switch).

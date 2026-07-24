---
description: Every endpoint the FastAPI read API exposes, with request and response shapes.
---

# API Reference

The read API runs at `http://localhost:8000` and also serves the built dashboard at
`/`. It serves the materialized state the daemon computes and performs only small,
per-board writes (track, ack, notes, toggles, reset, export, polling).

**Auth.** The whole origin is behind **HTTP Basic Auth** — the browser's native login
dialog, verified against the researcher table (see
[Configuration](../guides/configuration.md)). Every `/api` route below (and the static
app) requires it; `/healthz` is the only open path. Each request also carries the
browser's **board id** — the `X-Board-Id` header, or a `?board_id=` query param on the
SSE stream — which scopes the response to that board's own roster, notes, and picks.

## Endpoints At A Glance

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/healthz` | health check (the only unauthenticated route) |
| `GET`  | `/api/me/` | the authenticated researcher (id + username) |
| `GET`  | `/api/stream/` | the live Server-Sent Events stream (pushes which channels changed) |
| `GET`  | `/api/student_states/` | materialized per-student state (the dashboard's main read) |
| `GET`  | `/api/student_states/{id}/` | the heavy single-student payload (incl. the playground prompt and readable program) |
| `GET`  | `/api/tracked/` | the tracked-student roster |
| `POST` | `/api/tracked/` | track or untrack a student |
| `GET`  | `/api/triggers/` | active + recently-resolved intervention feed |
| `POST` | `/api/triggers/ack/` | dismiss a trigger |
| `GET`  | `/api/triggers/history/` | one student's full trigger history (the detail grid) |
| `GET`  | `/api/triggers/config/` | which trigger types are enabled |
| `POST` | `/api/triggers/config/` | enable or disable a trigger type |
| `GET`  | `/api/switches/` | identity switches (casing flips, new class codes) for tracked students |
| `POST` | `/api/switches/ack/` | dismiss an identity switch |
| `POST` | `/api/presence/` | toggle whether a student is present in the room |
| `POST` | `/api/picked/` | toggle whether a student has been picked/interviewed |
| `GET`  | `/api/notes/` | a student's notes |
| `POST` | `/api/notes/` | add a note |
| `GET`  | `/api/outbox/` | failed researcher inputs parked for replay |
| `POST` | `/api/outbox/` | park a failed researcher input |
| `POST` | `/api/export/` | download a zip of CSV snapshots of this board's data |
| `POST` | `/api/reset/` | clear THIS board's researcher data (notes, picks, acks); the shared mirror stays |
| `GET`  | `/api/polling/` | whether the daemon is currently polling production |
| `POST` | `/api/polling/` | pause or resume the daemon's production polling |

!!! tip "Responses are gzipped"
    Any JSON response over ~1KB is gzip-compressed when the client accepts it (the
    run arrays and playground payloads compress roughly 10x). The SSE stream is the
    one exception; it's sent uncompressed so events are never buffered.

---

## GET /healthz

Liveness check. It's at `/healthz` rather than `/` so the static dashboard can be
served from the root in remote builds.

```json title="Response"
{ "service": "luc-dashboard", "ok": true }
```

---

## GET /api/stream/

The live feed the dashboard actually runs on: one long-lived Server-Sent Events
connection instead of polling. On connect the server sends a `hello` (the client does
one full fetch), then it checks an O(1) per-channel change counter four times a
second and pushes a `changed` event naming only the channels that moved. The client
refetches just those endpoints.

```text title="Response stream (text/event-stream)"
event: hello
data: {}

event: changed
data: {"channels": ["triggers", "states"]}

: keepalive
```

The channels are `states`, `triggers`, `switches`, and `roster`, mapping to
`/api/student_states/`, `/api/triggers/`, `/api/switches/`, and `/api/tracked/`.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `once` | bool | return just the `hello` and close (used by tests) |

!!! note "The stream is the viewer heartbeat"
    While a dashboard holds this connection open, the server stamps this board's
    `viewer_last_seen` (on connect and every ~10 seconds), which is what the daemon's
    per-board dead-man's switch reads. A hidden tab closes the stream; if no dashboard
    is connected or polling, prod polling can wind down. See
    [Configuration](../guides/configuration.md#the-dead-mans-switch).

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
    A `GET` here also stamps `meta.viewer_last_seen`, and so does an open
    [`/api/stream/`](#get-apistream) connection. Either way, a fresh stamp means a
    dashboard is open, which is what the daemon's dead-man's switch reads. See
    [Configuration](../guides/configuration.md#the-dead-mans-switch).

---

## GET /api/student_states/{id}/

The heavy payload for one student. Same fields as a row above (including `display`,
the handle in its most-recent casing), plus the playground `block`:

```json title="Response (extra field)"
{
  "block": {
    "llm_prompt": "...",
    "timestamp": "2026-06-14T10:31:00",
    "readable": "when started\ndrive for forward, mm, amount 200\nturn for right, amount 90"
  }
}
```

`readable` is the student's latest blocks rendered as a program listing, with block
names from the official VEX mapping and every parameter spelled out, including the
numbers (how far they drive, how much they turn). Nested conditions render inline,
for example `if (not ((object distance < 200) and eye near object))`. It's
best-effort: an unparseable or missing snapshot yields `""`.

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
      "age_seconds": 360.0,
      "prev": { "trigger_type": "explorer", "label": "Explorer", "at": "2026-06-14T10:12:00" }
    }
  ],
  "active_count": 1,
  "counts": { "wheel_spin": 1 }
}
```

`prev` is the student's most recent trigger before this one (what it was and at what
time), so the alert card can show context at a glance. It's `null` for a student's
first-ever alert.

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

## GET /api/triggers/history/

One student's full trigger history for the session, newest first, open, resolved, and
dismissed alike. This is what the detail modal's trigger-history grid renders.

**Query parameters**

| Parameter | Type | Description |
|---|---|---|
| `studentID` | string | required; case-insensitive |

```json title="Response"
{
  "history": [
    { "id": 44, "trigger_type": "inactive", "label": "Inactive", "value": "idle 6m",
      "started_at": "2026-06-14T10:31:00", "resolved_at": null, "status": "active" },
    { "id": 42, "trigger_type": "wheel_spin", "label": "Wheel-spinning", "value": "6 identical reruns",
      "started_at": "2026-06-14T10:25:00", "resolved_at": "2026-06-14T10:27:00", "status": "dismissed" }
  ],
  "count": 2
}
```

`status` is `active` (still open), `resolved` (closed by new activity), or
`dismissed` (acknowledged by the researcher).

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

## GET /api/switches/

Identity switches detected for tracked students, newest first: a handle arriving in a
different casing (`cobra3` to `Cobra3`), or a handle turning up under a new class
code. These drive the dashboard's switch toasts and the Identity Switches feed.

```json title="Response"
{
  "switches": [
    { "id": 5, "studentID": "cobra3", "kind": "class",
      "from": "FPFVDH", "to": "AFURRR",
      "ts": "2026-06-14T10:31:00", "acknowledged": false }
  ],
  "unacked": 1
}
```

`kind` is `casing` or `class`. Identity is folded case-insensitively, so both
spellings are one student; the switch is the signal that the same handle is active
from a new spelling or class (often a shared device).

---

## POST /api/switches/ack/

Dismiss one identity switch so it stops showing as new.

```json title="Request"
{ "id": 5 }
```

Returns `{ "acknowledged": 1 }`.

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

## POST /api/outbox/

Park a researcher input whose write failed its retries. The dashboard calls this
automatically as the last step of its resilient-write path (see the
[read path](../concepts/read-path.md#resilient-writes-and-the-outbox)); you normally
never call it by hand. The raw payload is stored verbatim so the input can be
replayed later.

```json title="Request"
{ "op": "note on cobra3", "payload": { "studentID": "cobra3", "text": "..." }, "error": "Network Error" }
```

Returns `{ "stored": true }`.

---

## GET /api/outbox/

The parked failed inputs, newest first. The outbox is deliberately spared by
[reset](#post-apireset) and included in the CSV export, so a failed input survives
everything.

```json title="Response"
{
  "outbox": [
    { "id": 1, "op": "note on cobra3",
      "payload": "{\"studentID\": \"cobra3\", \"text\": \"...\"}",
      "error": "Network Error", "created_at": "2026-06-14 10:31:00" }
  ],
  "count": 1
}
```

---

## POST /api/export/

Download a **zip of CSV snapshots** of **this board's** data (one CSV per table: the
board's roster/notes/picks, plus the shared events, materialized state, and triggers
for the students it tracks). The zip is built entirely in memory and streamed to the
browser, so nothing is written to disk and the database is never touched. This is
**read-only** and safe to run any time.

```http title="Response"
200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename="lm-dashboard_export_2026-06-14_103100.zip"

<binary zip: student_state.csv, trigger_event.csv, vex_log.csv, ...>
```

---

## POST /api/reset/

Clear **this board's** researcher state for a fresh session: its notes, the
interview-pick state (picked toggles + pick history), and its trigger dismissals.
Its roster and presence stay. Unlike the old single-board reset, the **shared**
per-student mirror (`vex_log`, `student_state`, `trigger_event`) is left intact —
other boards depend on it, and this board just re-derives its view from it.

!!! info
    A CSV backup of this board (notes and picks included) is written to
    `exports/reset_<timestamp>/` before anything is cleared, so nothing is lost. The
    [outbox](#get-apioutbox) is deliberately spared. Production is untouched.

```json title="Response"
{
  "reset": true,
  "at": "2026-06-14T10:31:00",
  "backup": "/.../exports/reset_2026-06-14_103100"
}
```

---

## GET /api/polling/

Whether the daemon is polling production for **this board**. New boards default to
enabled.

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

Returns the new state, e.g. `{ "enabled": false }`. This is a per-board control flag
(stored in `workspace_setting`); production is untouched.

!!! note
    This is the *manual* pause. When the daemon runs with `--require-viewer` (the prod
    deployment arms it), there's also an *automatic* pause: prod polling stops for a
    board whenever its dashboard hasn't polled recently. The two are independent — the
    daemon polls a board only when it's manually enabled **and** a viewer is present. See
    [Configuration](../guides/configuration.md#the-dead-mans-switch).

---
description: Every endpoint the API serves, with its request and response.
---

# API Reference

The API runs at `http://localhost:8000` and serves the built dashboard at `/`. It returns what the
daemon worked out and makes only small writes for the caller's board. Every route is in
`app/main.py`.

## Before Any Call

Every `/api/` route needs the signed `ts_verified` cookie that a browser gets by passing Cloudflare
Turnstile (see [`POST /api/turnstile/verify/`](#post-apiturnstileverify)). Without it, a route
answers `403 {"error": "turnstile_required"}`, and the dashboard shows the check when it sees that.
`/healthz`, the static app and the verify route are open.

Each request also names the browser's board, in the `X-Board-Id` header or, for the stream, a
`?board_id=` query parameter. The answer is scoped to that board's roster, notes, picks and
settings. A request without a board ID acts on one shared default board.

A board set to a ZANY study answers `403 {"detail": "zany_locked"}` on every route except
`/api/source/` and `/api/zany/*` until its browser unlocks ZANY.

Every board-scoped read shows only the board's source, only activity since its last reset, and
only the trigger types it shows.

## All Endpoints

| Method | Path | What it does |
|--------|------|---------|
| `GET`  | `/healthz` | health check, outside the Turnstile gate |
| `POST` | `/api/turnstile/verify/` | pass the Turnstile check and get the cookie |
| `GET`  | `/api/source/` | which logs this board listens to |
| `POST` | `/api/source/` | point this board at Reflecks or one ZANY study |
| `GET`  | `/api/zany/` | whether ZANY is connected and unlocked here, and its studies |
| `POST` | `/api/zany/unlock/` | unlock ZANY in this browser with the research login |
| `POST` | `/api/zany/lock/` | lock it again |
| `GET`  | `/api/zany/participants/` | the participant IDs with records in one study |
| `GET`  | `/api/stream/` | the live stream that says which channels changed |
| `GET`  | `/api/student_states/` | the state of every student on the board |
| `GET`  | `/api/student_states/{student_id}/` | one student's full payload, with the program and goal evidence |
| `GET`  | `/api/tracked/` | the board's roster |
| `POST` | `/api/tracked/` | track or untrack a student |
| `GET`  | `/api/triggers/` | the alert feed |
| `POST` | `/api/triggers/ack/` | dismiss an alert, or all of a student's |
| `GET`  | `/api/triggers/history/` | one student's alert history |
| `GET`  | `/api/triggers/config/` | which trigger types this board shows |
| `POST` | `/api/triggers/config/` | show or hide a trigger type on this board |
| `GET`  | `/api/switches/` | identity switches for the board's students |
| `POST` | `/api/switches/ack/` | dismiss an identity switch |
| `POST` | `/api/presence/` | set whether a student is in the room |
| `POST` | `/api/picked/` | set whether a student was picked for an interview |
| `GET`  | `/api/notes/` | a student's notes |
| `POST` | `/api/notes/` | add a note |
| `GET`  | `/api/outbox/` | the inputs that failed to save |
| `POST` | `/api/outbox/` | park an input that failed to save |
| `POST` | `/api/export/` | download a zip of CSV files of this board's data |
| `POST` | `/api/reset/` | start this board fresh |
| `GET`  | `/api/polling/` | whether the daemon polls production for this board |
| `POST` | `/api/polling/` | pause or resume that polling |

!!! tip "Responses are gzipped"
    Any response over about 1 KB is gzipped when the client accepts it. The stream is the one
    exception, so events are never held back.

---

## GET /healthz

A health check. It lives at `/healthz` and not `/` because the dashboard is served from `/`.

```json title="Response"
{ "service": "luc-dashboard", "ok": true }
```

---

## POST /api/turnstile/verify/

Checks a Turnstile widget token with Cloudflare. On success it sets `ts_verified`, a signed,
HTTP-only cookie that lasts 12 hours.

```json title="Request"
{ "token": "<the widget's response token>" }
```

Returns `{ "ok": true }`, or `403` when Cloudflare rejects the token.

---

## GET /api/source/

Which logs this board listens to. That is `"reflecks"` (VEXcode VR), or one ZANY study as
`"zany:<study>"`.

```json title="Response"
{ "source": "reflecks" }
```

---

## POST /api/source/

Points this board at Reflecks or at one ZANY study. Each source keeps its own roster.

```json title="Request"
{ "source": "zany:STUDY-0001" }
```

Returns `{ "source": "zany:STUDY-0001" }`. It answers `400` for an unknown source or a study with
no records, `403 zany_locked` when this browser hasn't unlocked ZANY, and `503` when ZANY's store
doesn't answer.

---

## GET /api/zany/

Whether this server can read ZANY's logs (`enabled`, set by `ZANY_LOG_DSN`), whether this browser
unlocked them, and once it has, the studies with records, newest activity first.

```json title="Response"
{
  "enabled": true,
  "unlocked": true,
  "studies": [
    { "study": "STUDY-0001", "code": "ZX42", "participants": 18, "last": "2026-11-20T15:02:11+00:00" }
  ]
}
```

`code` is the class code students type in ZANY. It answers `503` when the store doesn't answer.

---

## POST /api/zany/unlock/

Unlocks ZANY's logs in this browser with the research login, which ATLAS-invite checks. On success
it sets a signed, HTTP-only `zany_unlocked` cookie that lasts 12 hours.

```json title="Request"
{ "email": "researcher@example.edu", "password": "..." }
```

Returns `{ "unlocked": true, "studies": [...] }`. It answers `401` with the reason for a wrong
login, `404` when ZANY isn't connected here, and `429` after five wrong tries from one address in
ten minutes.

---

## POST /api/zany/lock/

Clears the unlock cookie. Returns `{ "unlocked": false }`.

---

## GET /api/zany/participants/

Takes `?study=STUDY-0001` and returns the participant IDs with records in that study, sorted, for
**Track everyone in**. The browser must be unlocked.

```json title="Response"
{ "participants": ["R01", "R02", "R03"] }
```

---

## GET /api/stream/

The live stream the dashboard runs on, as Server-Sent Events. On connect the server sends `hello`,
and the client fetches everything once. After that the server checks the change counters four
times a second and sends `changed` with the channels that moved. Every 10 seconds it sends a
keepalive comment.

```text title="Response (text/event-stream)"
event: hello
data: {}

event: changed
data: {"channels": ["triggers", "states"]}

: keepalive
```

The channels are `states`, `triggers`, `switches` and `roster`. They match
`/api/student_states/`, `/api/triggers/`, `/api/switches/` and `/api/tracked/`.

| Parameter | Type | What it does |
|---|---|---|
| `board_id` | string | the board, since `EventSource` can't send headers |
| `once` | bool | send `hello` and close, which the tests use |

!!! note "The stream is the viewer heartbeat"
    While a dashboard holds the stream, the server stamps the board's `viewer_last_seen` on
    connect and every 10 seconds. The daemon's dead-man's switch reads that stamp. See
    [Configuration](../guides/configuration.md#the-dead-mans-switch).

---

## GET /api/student_states/

The dashboard's main read. It returns the state of every student on the board, newest activity
first.

| Parameter | Type | What it does |
|---|---|---|
| `classCode` | string | only students with this class code |

```json title="Response"
{
  "students": [
    {
      "studentID": "cobra3",
      "display": "Cobra3",
      "classCode": "FPFVDH",
      "run_count": 3,
      "event_count": 240,
      "last_seen": "2026-06-14T10:31:00+00:00",
      "runs": {
        "runs": [
          { "index": 0, "edit_distance": null, "ts": 1781432400.0, "playground": "CastleCrasherPlus" },
          { "index": 1, "edit_distance": 0, "ts": 1781432520.0, "playground": "CastleCrasherPlus" },
          { "index": 2, "edit_distance": 7, "ts": 1781432700.0, "playground": "CastleCrasherPlus" }
        ],
        "run_count": 3
      },
      "episodes": { "episodes": [], "pauses": [], "event_count": 240, "episode_count": 0, "pause_count": 0 },
      "updated_at": "2026-06-14T10:31:01+00:00"
    }
  ],
  "student_count": 1
}
```

Each run's `edit_distance` is the APTED tree edit distance from the run before it, and `null` for
the first run on a playground. Run times are epoch seconds. There is no status field, because the
dashboard works out the headline from the alert feed. This is the light shape, without the program,
which comes from the single-student endpoint.

!!! note "Viewer heartbeat"
    Each call here also stamps the board's `viewer_last_seen`, as an open stream does.

---

## GET /api/student_states/{student_id}/

One student's full payload, which the student sheet fetches when it opens. It has the fields of a
row above plus the program in `block`.

```json title="Response (extra fields)"
{
  "block": {
    "llm_prompt": "...",
    "timestamp": "2026-06-14T10:31:00+00:00",
    "readable": "when started\ndrive for forward, mm, amount 200\nturn for right, amount 90"
  },
  "goal_recognition_enabled": true,
  "goal_runs": [
    {
      "index": 4,
      "goals": [{ "goal": "engage_plow", "indicators": [{ "name": "plow_approach_intent", "rung": "near", "flags": ["sim_unverified"] }] }],
      "timeline": { "events": [], "post_exit_events": [] },
      "battery": { "eligible": true, "qualifying_blocks": [], "scenarios": [] },
      "rollup": { "provisional": false, "goals": [] },
      "rubric": { "provisional": true, "status": "provisional", "dimensions": [] },
      "summary": { "boundary_exceeded": false, "fidelity_verdict": "agree" }
    }
  ]
}
```

`readable` is the student's latest blocks as a program listing, with block names from the official
VEX mapping and every value spelled out, including how far the robot drives and how much it turns.
Nested conditions print inline, like `if (not ((object distance < 200) and eye near object))`. A
snapshot that is missing or can't be parsed gives `""`.

`goal_runs` has one entry per profiled Castle Crashers run since the board's reset. Each lists every
goal's indicators with the rung reached and their uncertainty flags, the rung-change `timeline`,
the sensor test `battery`, the claim per goal (`rollup`), the provisional execution `rubric`, and
facts about the run (`summary`), such as whether the robot left the island. It is `[]` when goal
recognition is off (`GOAL_RECOGNITION_ENABLED=0`) or shaping fails.

It answers `404` when the student isn't on the board or has no state yet.

---

## GET /api/tracked/

The board's roster for its current source.

```json title="Response"
{
  "tracked": [
    {
      "studentID": "cobra3",
      "display": "Cobra3",
      "backfilled": true,
      "has_data": true,
      "present": true,
      "picked": false,
      "picked_at": null
    }
  ],
  "count": 1,
  "source": "reflecks"
}
```

---

## POST /api/tracked/

Tracks or untracks a student on this board. Tracking starts a one-time backfill in the daemon. On
a ZANY board, an ID is a participant ID in the board's study.

```json title="Track a student"
{ "studentID": "cobra3" }
```

```json title="Untrack a student"
{ "studentID": "cobra3", "remove": true }
```

Returns `{ "added": "cobra3" }` or `{ "removed": "cobra3" }`. Untracking deletes the student's
shared data only when no other board tracks them. A missing `studentID` answers `400`.

---

## GET /api/triggers/

The alert feed. It has open alerts and those resolved in the last 7 minutes, newest first, that
this board hasn't dismissed, of the types it shows.

```json title="Response"
{
  "triggers": [
    {
      "id": 42,
      "studentID": "cobra3",
      "trigger_type": "wheel_spin",
      "label": "Wheel-spinning",
      "value": "6 identical reruns",
      "started_at": "2026-06-14T10:25:00+00:00",
      "resolved_at": null,
      "active": true,
      "age_seconds": 360.0,
      "prev": { "trigger_type": "explorer", "label": "Explorer", "at": "2026-06-14T10:12:00+00:00" }
    }
  ],
  "active_count": 1,
  "counts": { "wheel_spin": 1 }
}
```

`prev` is the student's alert before this one, so the feed can show it. It is `null` for a
student's first alert. `counts` counts the open alerts by type.

| `trigger_type` | Label | Fires when | Example `value` |
|---|---|---|---|
| `wheel_spin` | Wheel-spinning | 6 runs in a row with `edit_distance == 0` | `6 identical reruns` |
| `resilience` | Resilience | an edit after 4 or more zeros | `recovered after 5 reruns` |
| `inactive` | Inactive | idle for 240 seconds | `idle 7m` |
| `explorer` | Explorer | a run with `edit_distance >= 13` | `changed 21` |
| `iterative` | Step-by-Step | the playground's count of runs with `edit_distance >= 1` (6 by default) | `6 steady edits` |

The first four are momentary, with one row per run that fires them. `inactive` is sustained. It
stays open while the student is idle and opens again after 10 minutes if it was dismissed and the
student is still idle.

---

## POST /api/triggers/ack/

Dismisses one alert by `id`, or every alert of one student, for this board.

```json title="By id"
{ "id": 42 }
```

```json title="By student"
{ "studentID": "cobra3" }
```

Returns `{ "acknowledged": n }`. Sending neither answers `400`.

---

## GET /api/triggers/history/

One student's alert history since the board's reset, newest first, whether open, resolved or
dismissed. The student sheet shows it.

| Parameter | Type | What it does |
|---|---|---|
| `studentID` | string | required, and case doesn't matter |

```json title="Response"
{
  "history": [
    { "id": 44, "trigger_type": "inactive", "label": "Inactive", "value": "idle 6m",
      "started_at": "2026-06-14T10:31:00+00:00", "resolved_at": null, "status": "active" },
    { "id": 42, "trigger_type": "wheel_spin", "label": "Wheel-spinning", "value": "6 identical reruns",
      "started_at": "2026-06-14T10:25:00+00:00", "resolved_at": "2026-06-14T10:25:00+00:00", "status": "dismissed" }
  ],
  "count": 2
}
```

`status` is `active` (still open), `resolved` (closed by new activity, or a momentary alert) or
`dismissed`.

---

## GET /api/triggers/config/

Which trigger types this board shows, all of them by default, with their labels.

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

Shows or hides one trigger type on this board. The daemon keeps firing every type, because alerts
are shared by all boards, so this only filters this board's [feed](#get-apitriggers). Showing a
type again brings back its alerts that are still current. A board that never set its own switches
uses the shared setting from before the switches were per board.

```json title="Request"
{ "trigger_type": "inactive", "enabled": false }
```

Returns the full `enabled` map. An unknown `trigger_type` answers `400`.

---

## GET /api/switches/

Identity switches for the board's students, newest first, up to 100. A switch is an ID that arrives
in a different casing (`cobra3` to `Cobra3`) or under a new class code.

```json title="Response"
{
  "switches": [
    { "id": 5, "studentID": "cobra3", "kind": "class",
      "from": "FPFVDH", "to": "AFURRR",
      "ts": "2026-06-14T10:31:00+00:00", "acknowledged": false }
  ],
  "unacked": 1
}
```

`kind` is `casing` or `class`.

---

## POST /api/switches/ack/

Dismisses one identity switch so it no longer shows as new. The dismissal is shared by every board.

```json title="Request"
{ "id": 5 }
```

Returns `{ "acknowledged": 1 }`.

---

## POST /api/presence/

Sets whether a tracked student is in the room, on this board.

```json title="Request"
{ "studentID": "cobra3", "present": false }
```

Returns `{ "studentID": "cobra3", "present": false }`. A missing `studentID` answers `400`.

---

## POST /api/picked/

Sets whether a tracked student was picked for an interview this session, on this board. It sets
`picked_at` on the roster row and adds a row to `pick_event`, which records where the pick came
from.

```json title="Request"
{ "studentID": "cobra3", "picked": true, "source": "intervention", "trigger_id": 42, "trigger_type": "wheel_spin" }
```

`source` is `roster` (the default, from a card) or `intervention` (from an alert, with the alert's
`trigger_id` and `trigger_type`). Returns `{ "studentID": "cobra3", "picked": true }`. A missing
`studentID` answers `400`.

---

## GET /api/notes/

This board's notes for one student, oldest first.

| Parameter | Type | What it does |
|---|---|---|
| `studentID` | string | required |

```json title="Response"
{
  "notes": [
    { "id": 1, "studentID": "cobra3", "ts": "2026-06-14T10:31:00+00:00", "text": "talked through the loop",
      "trigger_id": null, "trigger_type": null, "created_at": "2026-06-14T10:31:00+00:00" }
  ],
  "count": 1
}
```

A missing `studentID` answers `400`.

---

## POST /api/notes/

Adds a note for a student on this board. Send `trigger_id` and `trigger_type` to tie it to the
alert it was written from, or leave both out.

```json title="Request"
{ "studentID": "cobra3", "text": "talked through the loop", "trigger_id": 42, "trigger_type": "wheel_spin" }
```

Returns the new note. A missing `studentID` or empty `text` answers `400`.

---

## POST /api/outbox/

Parks an input whose write failed every retry. The dashboard calls this itself as the last step of
[saving a researcher's input](../concepts/read-path.md#saving-a-researchers-input). The payload is
stored as sent, so the input can be replayed by hand.

```json title="Request"
{ "op": "note on cobra3", "payload": { "studentID": "cobra3", "text": "..." }, "error": "Network Error" }
```

Returns `{ "stored": true }`.

---

## GET /api/outbox/

This board's parked inputs, newest first, up to 200. Reset leaves the outbox alone, and the export
includes it.

```json title="Response"
{
  "outbox": [
    { "id": 1, "op": "note on cobra3",
      "payload": "{\"studentID\": \"cobra3\", \"text\": \"...\"}",
      "error": "Network Error", "created_at": "2026-06-14T10:31:00+00:00" }
  ],
  "count": 1
}
```

---

## POST /api/export/

Downloads a zip with one CSV per table. It has this board's roster, notes, picks and dismissals,
and the events, state, alerts, goal evidence and switches of the students it tracks. The zip is
built in memory, and nothing is written.

```http title="Response"
200 OK
Content-Type: application/zip
Content-Disposition: attachment; filename="lm-dashboard_export_2026-06-14_103100.zip"

<zip: tracked_student.csv, note.csv, pick_event.csv, student_state.csv, vex_log.csv, ...>
```

---

## POST /api/reset/

Starts this board fresh. It clears the board's notes, picks and pick history, and its dismissals,
and from then on every read shows only activity after the reset. The roster and presence stay, and
the shared student data stays, since other boards use it.

!!! info
    Before it clears anything, it saves the same zip [export](#post-apiexport) gives, notes and
    picks included, to `exports/reset_<timestamp>.zip`. Those zips live in the `exports` volume, so
    a rebuild keeps them. The [outbox](#get-apioutbox) is left alone. Production is never
    touched.

```json title="Response"
{
  "reset": true,
  "at": "2026-06-14T10:31:00+00:00",
  "backup": "/app/exports/reset_2026-06-14_103100.zip"
}
```

---

## GET /api/polling/

Whether the daemon polls production for this board. A new board starts with it on.

```json title="Response"
{ "enabled": true }
```

---

## POST /api/polling/

Pauses or resumes the daemon's production polling for this board. While it is paused, the daemon
makes no production calls for the board. It picks up again within about a second of resuming, and
backfills the board's students to fill the gap.

```json title="Pause"
{ "enabled": false }
```

Returns the new state, like `{ "enabled": false }`.

!!! note
    This is the manual pause. With `--require-viewer`, which `compose.yml` turns on, the daemon
    also stops polling a board whose dashboard nobody has open. It polls a board only when both
    allow it. See [Configuration](../guides/configuration.md#the-dead-mans-switch).

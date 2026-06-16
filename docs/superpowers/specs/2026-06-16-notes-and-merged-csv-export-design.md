# Notes / observations + single merged CSV export

## Overview

Add per-learner notes to the dashboard so a researcher can jot observations,
including ones written while responding to an active intervention alert, and read
all of a learner's notes in one place. Plus, make Export produce one merged
`all_data.csv` containing every table, alongside the existing per-table CSVs.

This is researcher-entered annotation, not data derived from production, so it is
owned by the API (like the tracked roster, acks, reset, polling, and the
present/picked toggles). The daemon needs no changes.

## Notes data model

New table:

```
note(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID    VARCHAR(128) NOT NULL,
    ts           DATETIME NOT NULL,        -- when the observation was made
    text         TEXT NOT NULL,
    trigger_id   INTEGER,                  -- the alert it was written from (nullable)
    trigger_type VARCHAR(24),              -- denormalized so it survives a reset
    created_at   DATETIME NOT NULL
)
```

- Append-only log. One row per note. Many notes per learner.
- `trigger_id` / `trigger_type` are set when the note is written from an active
  alert in the right column, and null for a manually-added note.
- `trigger_type` is stored even though `trigger_id` exists, so the context label
  survives even after the linked `trigger_event` row is cleared.
- Added via `CREATE TABLE IF NOT EXISTS` in `_SCHEMA`; since it is a brand new
  table, no `ALTER` migration is needed (unlike the present/picked columns).

### Reset behavior (decision to confirm)

`reset_all()` currently wipes `trigger_event`, `student_state`, `vex_log`,
`message` and keeps `tracked_student`, `ingest_cursor`, `meta`. **Notes are
research data, so reset will NOT delete them** (the `note` table is kept, like the
roster). A reset can therefore leave a note whose `trigger_id` no longer resolves;
that is fine because the note carries `trigger_type` and its own text.

## API

New endpoints in `app/main.py`, backed by new functions in `app/db.py`:

| Method | Path | Body / query | Returns |
|---|---|---|---|
| `POST` | `/api/notes/` | `{studentID, text, trigger_id?, trigger_type?}` | the created note row |
| `GET`  | `/api/notes/` | `?studentID=X` | `{notes: [...], count}` oldest to newest |

- `POST` stamps `ts` and `created_at` server-side. Rejects missing `studentID` or
  empty `text` with 400.
- Reused, unchanged: **Picked** = `POST /api/picked/`, **dismiss** =
  `POST /api/triggers/ack/`.

New `db.py` functions: `add_note(studentID, text, trigger_id=None,
trigger_type=None)` and `list_notes(studentID)`.

## UI (frontend/src/CohortDashboard.jsx)

### Right column (each alert item)
- A small **note editor**: a textarea plus a Save button. Saving posts a note
  linked to that alert's `trigger_id` and `trigger_type`.
- The shared **Picked** toggle (same state as the learner's main card, via the
  existing `setPicked`).
- **Dismiss (X)**: this is the existing ack. Acking removes the alert from the
  feed and collapses its note editor. Any note already saved persists.

### Main board card
- No change beyond the existing shared **Picked** toggle.

### Detail modal (click a learner)
- A **notes log**: every note for that learner, oldest to newest, each showing its
  timestamp and, if present, the alert/trigger it was written during.
- An **add-a-manual-note** box (textarea plus Save) that posts a note with no
  trigger link.

### Data flow
- Notes for the selected learner are fetched when the modal opens and refetched
  after a successful post. Right-column note saves also refetch if that learner's
  modal is open. No new polling timer is required.

## Export: single merged CSV

Export keeps writing the per-table CSVs and additionally writes **`all_data.csv`**
into the same `exports/export_<timestamp>/` directory.

`all_data.csv` is a **wide union**:
- First column `source_table` names the originating table (`vex_log`,
  `student_state`, `trigger_event`, `tracked_student`, `note`, `ingest_cursor`,
  `meta`, ...).
- Remaining columns are the union of all columns across all tables, in a stable
  order. Cells are blank where a column does not apply to that row's table.
- Columns that share a name across tables (`id`, `studentID`, `created_at`,
  `detail`, ...) map to the same output column.
- Rows are sorted by `studentID` then by a best-effort per-row timestamp (the
  first present of `ts`, `started_at`, `received_at`, `updated_at`, `created_at`),
  so the file reads as a per-learner chronology with notes next to their alerts.
  Rows with no studentID (for example `meta`, `ingest_cursor`) sort to the end.

Same `_EXPORT_SKIP` set (sqlite internal tables) is excluded. Implementation lives
in `app/db.py` next to `export_csv`; `POST /api/export/` and
`scripts/export_csv.py` both produce the per-table files plus `all_data.csv`.

## Files touched

- `app/db.py`: `note` table in `_SCHEMA`; `add_note`, `list_notes`; merged-CSV
  writer; confirm `reset_all` leaves `note` intact.
- `app/main.py`: `NoteBody` model; `POST /api/notes/`, `GET /api/notes/`.
- `frontend/src/CohortDashboard.jsx`: right-column note editor + Picked toggle +
  ack-collapses-editor; detail-modal notes log + manual-note box; notes
  fetch/post handlers and styles.
- `scripts/export_csv.py`: ensure it emits `all_data.csv` too (if it calls the
  shared db function, this is automatic).

## Edge cases

- Empty note text or missing studentID: 400, nothing written.
- Note linked to a trigger that is later cleared: link dangles harmlessly; text +
  `trigger_type` remain.
- A learner with no notes: detail modal shows an empty-state message and the
  manual-note box.
- Large `vex_log`: `all_data.csv` can be big for an active session. Acceptable for
  classroom scale; it is post-processed, not skimmed.

## Verification (matches this project's pattern: API smoke + frontend build)

1. Start the API. `POST /api/notes/` with a trigger link and again without one;
   `GET /api/notes/?studentID=...` returns both oldest to newest.
2. `POST /api/export/`: confirm `all_data.csv` exists with a `source_table` first
   column, includes `note` rows, and that `note.csv` also exists.
3. Run a reset, confirm notes are still present afterward.
4. `npm run build` is clean; manual click-through of the right-column editor,
   Picked sharing, dismiss-collapses-editor, and the detail-modal log.

## Out of scope (not building now)

Pick-next button, the "how to pick" selection rule, randomized pick, presence
toggle changes, interviewer/session tagging on notes. These remain in
`RESEARCH_PLAN.md` as future work.

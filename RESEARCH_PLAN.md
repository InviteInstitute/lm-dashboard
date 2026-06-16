# Research Feature Plan

Planned research-facing features for the LM Dashboard, organized from the team's
notes (incl. Chris Palaguachi's input). This is the shared "how it'll work" doc.

**Status:** ✅ built · 🔨 in progress · ⬜ planned
**Effort:** S (small) · M (medium) · L (large)

---

## 1. Interview workflow

These pieces are one connected feature — *manage a pool of present students → pick
one → mark them done → log it for analysis* — so they should be built together,
not separately. They all read/write the same per-student, per-session state.

| Sub-feature | What it does | Lives | Effort | Status |
|---|---|---|---|---|
| **Presence toggle** | Green/red toggle per student ID (present/absent); absent students hide from the board so you're not scrolling 20+ names | FE + a `present` flag | S | ⬜ |
| **Log interview selection** | Clicking a student during an interview records `{time, studentID, what was clicked, interviewer, session}`; exportable for analysis. *(Chris: clicking to go to a student doubles as a logged event you can filter the day afterward.)* | FE click → BE table → CSV | M | ⬜ |
| **"How to pick a kid"** | A defined selection rule — e.g. prioritize flagged (wheel-spinning) students, then fall back to random | product decision | S | ⬜ |
| **Mark "picked"** | Flag a student as already interviewed (visual mark) so they drop out of the pick pool | FE + BE flag | S | ⬜ |
| **Randomized pick (backup)** | "Pick a random student" button — chooses a random *present, not-yet-picked* student when no one is obviously flagged | FE (uses the flags above) | S | ⬜ |

## 3. Student onboarding — playground deep-link

| Feature | What it does | Effort | Status |
|---|---|---|---|
| **Pre-filled playground link** | Instead of handing each student an ID to type into the VEX playground manually, generate a URL like `…/playground?studentID=<id>` plus a "copy link" button per student. **Blocked on:** confirming the VEX playground/viewer actually reads a `studentID` URL param (old reflecks TODO: *"Test url params for VEX playgrounds"*). | S (our side) | ⬜ |

## 4. End-of-day data export ✅

A script to dump the local SQLite database to CSV files so the data is easy to work
with in Excel / pandas at the end of the day.

```bash
python scripts/export_csv.py                   # → exports/<YYYY-MM-DD_HHMM>/<table>.csv
python scripts/export_csv.py --out data/today  # choose the output folder
python scripts/export_csv.py --tables student_state,trigger_event
```

- One CSV per table (`vex_log`, `student_state`, `trigger_event`, `tracked_student`,
  …, and the interview-selection log once #1 ships).
- JSON columns (`runs` / `episodes` / `detail`) are written as raw JSON text — load
  with `json.loads` in pandas, or treat as text in a spreadsheet.
- **Read-only** (never touches the DB). Output goes to `exports/`, which is
  git-ignored so student data is never committed.

> Tip: the interview-selection log (#1) lands in the DB, so it exports to CSV
> automatically via this same script — no separate tooling needed.

---

## Decisions to make (before building #1)

1. **Persist or ephemeral?** Should present/picked state survive a refresh and be
   shared across everyone viewing the dashboard (→ store in the DB), or be
   per-browser only (→ localStorage)? *Recommend DB-persisted for reproducibility.*
2. **What counts as an "interview log"?** Every card click (simple but noisy), or an
   explicit **"Interview mode" / "Log this"** action so idle browsing isn't recorded?
   *Recommend an explicit action / interview-mode toggle.*
3. **Storage shape:** a raw appended `.csv` is simplest; a small DB table + the
   `export_csv.py` dump is queryable and matches "filter afterward."
   *Recommend the DB table (it exports to CSV for free).*
4. **Sessions:** tag logs by **day/session + interviewer name** so multiple
   researchers/days don't mix? *Probably yes.*

## Suggested build order

1. **Presence toggle** — smallest, immediately useful, unblocks the pick pool.
2. **Pick + mark-picked + random-pick + selection logging** — one unit, the core loop.
3. **CSV export of the interview log** — free once it's a DB table (use `export_csv.py`).
4. **Playground deep-link** — pending VEX-side param confirmation.

✅ Already done: **end-of-day data export** (`scripts/export_csv.py`).

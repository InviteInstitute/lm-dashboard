---
description: Student cards, the who-needs-help column, drill-down detail, and the reset button.
---

# Using The Dashboard

The dashboard is a single screen at [http://localhost:3000](http://localhost:3000).
Everything on it comes from the same handful of polled endpoints, so the whole view
stays in sync with itself.

## Track A Student

Type a student ID into **Track a student**. The daemon backfills their recent
history, materializes their state, and their card shows up within a tick or two.
Removing a student stops tracking them and deletes their local data.

## Student Cards

There's one card per tracked student, kept in a stable order so a card never jumps
around when its own data updates (present students sort first, then alphabetically by
ID). Each card shows four things:

| Element | What It Shows |
|---|---|
| **Strategy state** | the current HMM state: Iterator, Explorer, or Stuck |
| **Strategy sparkline** | the per-run HMM state sequence over time |
| **Episode sparkline** | the segmented code / run / reset timeline |
| **Counts** | run and event totals for the session |

Each card also carries **Present** and **Picked** toggles for the interview workflow.
Marking a student absent dims their card and drops it to the bottom; marking them
picked records that you've interviewed them this session (with a timestamp).

### What The Strategy States Mean

| State | Label | How To Read It |
|---|---|---|
| 0 | Iterator | steady, incremental edits between runs |
| 1 | Explorer | bigger structural changes, trying new approaches |
| 2 | Stuck | wheel-spinning, not much productive change |

## Who-Needs-Help Column

The column on the right is the live intervention feed. It shows every alert the daemon
has fired that hasn't yet resolved or been acknowledged.

| Trigger | Colour | Fires When |
|---|---|---|
| **Wheel-spinning** | red `⟳` | the HMM puts the student in the *stuck* state |
| **Inactive** | amber `⏸` | no events for 5 minutes or more |
| **Big rewrite** | purple `✎` | a single run's `change_score` hits 0.5 or higher |

Each row shows the student ID, the trigger label and its value (something like
`3 re-runs` for wheel-spin, `idle 7m` for inactive, `change 0.71` for a big rewrite),
and how long ago it fired. Click a row to open that student's detail, hit the **✕** to
dismiss the alert, or use **Notes** to jot an observation right against the alert.

!!! note "Re-Alert"
    Acking a sustained trigger (wheel-spin or inactive) doesn't silence it forever.
    If the condition keeps holding for another 10 minutes, the daemon closes the acked
    row and opens a fresh one, so a student who never actually got unstuck comes back
    to the feed.

You can also turn whole trigger types on or off from the **⚙ Triggers** button in the
top bar. Switching one off tells the daemon to stop firing it and clear its open
alerts.

## Pause / Resume Polling

The top bar has a **⏸ Pause polling** toggle. Pausing tells the daemon to stop hitting
the production server completely. It makes zero requests to prod while paused, keeps
showing the last data it pulled, and picks back up within about a second of you
clicking **▶ Resume polling**. While it's off, the status dot turns amber and a
"Daemon Paused" label shows up next to the title.

!!! tip
    Use this between sessions. The daemon polls production the whole time it's running,
    even during quiet stretches, which is a constant load on prod. Pausing when no
    class is active gives prod room to recover, which really matters if it's on a
    CPU-credit (burstable) instance. The toggle is shared, so every open dashboard
    sees the same state.

The daemon process keeps running while paused. Pausing only stops the polling, not the
daemon itself.

## Drill-Down

Click any card to open the full detail:

- The **playground prompt**, which is their current code described in plain language
  for an LLM.
- Full-size **episode** and **strategy** timelines.
- The complete **notes and observations** log for that student, with a box to add
  more.

The detail view fetches its own per-student payload on open and keeps it refreshed
while the modal is up.

## Export

The **⬇ Export** button writes a CSV snapshot of the data (raw events, materialized
state, triggers, roster, notes) to `exports/export_<timestamp>/`. It's read-only, so
the database is never touched and you can run it any time. A success dialog tells you
where it landed.

## Reset

The **↺ Reset** button clears all the locally-stored events, episodes, strategy state,
flags, and notes, and tells the daemon to drop its in-memory workers so the board
starts fresh from new activity.

!!! info
    Reset writes a CSV backup (notes included) to `exports/reset_<timestamp>/` before
    it wipes, so nothing is actually lost. It's local only, production is never
    touched. The raw event cursor stays put, so the board rebuilds only from activity
    that arrives after the reset, and tracked students stay tracked.

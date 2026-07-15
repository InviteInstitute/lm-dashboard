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

There's one card per tracked student, ordered by most recent activity (present
students sort ahead of absent ones). Each card shows:

| Element | What It Shows |
|---|---|
| **Status badge** | the student's headline state, derived from their active triggers (or **OK** when none are firing) |
| **Run track** | one tile per run, coloured by that run's edit distance |
| **Episode sparkline** | the segmented code / run / reset timeline, with pauses |
| **Counts** | run and event totals for the session |

Each card also carries **Present** and **Picked** toggles for the interview workflow.
Marking a student absent dims their card and drops it down; marking them picked records
that you've interviewed them this session (with a timestamp).

### Reading The Run Track

Each run is coloured by its **edit distance** from the run before it, the number of
blocks that changed:

| Colour | Edit distance | How To Read It |
|---|---|---|
| grey | `0` | identical re-run, no change |
| blue | small | an incremental edit |
| purple | `>= 13` | a large, structural change |

There's no strategy model behind this: the colour is the raw number of block edits,
and the five triggers are just rules over the sequence of those numbers.

## Who-Needs-Help Column

The column on the right is the live intervention feed. It shows every alert the daemon
has fired that hasn't yet resolved or been acknowledged. There are five:

| Trigger | Fires When | Example value |
|---|---|---|
| **Wheel-spinning** | six or more identical re-runs in a row (`edit_distance == 0`) | `6 identical reruns` |
| **Resilience** | a real edit right after four or more identical re-runs | `recovered after 5 reruns` |
| **Inactive** | no events for four minutes (240s) or more | `idle 7m` |
| **Explorer** | a single run changes 13 or more blocks | `changed 21` |
| **Step-by-Step** | six runs of steady editing (`edit_distance >= 1`) | `6 steady edits` |

Each row shows the student ID, the trigger label and its value, and how long ago it
fired. Click a row to open that student's detail, hit the **✕** to dismiss the alert,
or use **Notes** to jot an observation right against the alert.

!!! note "Wheel-spinning and Resilience are a pair"
    They read the same streak from opposite ends: wheel-spinning fires while a student
    re-runs identical code, and resilience fires the moment they finally make a real
    edit. On a run of six zeros followed by an edit you'll see both, which is by design.

!!! note "Re-Alert"
    Acking the **inactive** alert doesn't silence it forever. If the student stays idle
    for another 10 minutes, the daemon closes the acked row and opens a fresh one, so
    someone who never came back keeps resurfacing in the feed.

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
- Full-size **run** and **episode** timelines.
- The complete **notes and observations** log for that student, with a box to add
  more.

The detail view fetches its own per-student payload on open and keeps it refreshed
while the modal is up.

## Export

The **⬇ Export** button downloads a **zip of CSV snapshots** (raw events, materialized
state, triggers, roster, notes) straight to your computer. It's built in memory and is
read-only, so the database is never touched and nothing is written to the server, you
can run it any time. The file is named `lm-dashboard_export_<timestamp>.zip`.

## Reset

The **↺ Reset** button clears all the locally-stored events, episodes, run state,
flags, and notes, and tells the daemon to drop its in-memory workers so the board
starts fresh from new activity.

!!! info
    Reset writes a CSV backup (notes included) to `exports/reset_<timestamp>/` on the
    server before it wipes, so nothing is actually lost. It's local only, production is
    never touched. The raw event cursor stays put, so the board rebuilds only from
    activity that arrives after the reset, and tracked students stay tracked.

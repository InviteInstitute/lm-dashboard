---
description: Student cards, the who-needs-help column, drill-down detail, and the reset button.
---

# Using the dashboard

The dashboard is a single screen at
[http://localhost:3000](http://localhost:3000). Everything on it comes from one
polled payload, so the whole view stays in sync with itself.

## Track a student

Type a student ID into **Track a student**. The daemon backfills their recent
history, materializes their state, and their card shows up within a tick or two.
Removing a student stops tracking them and deletes their local data.

## Student cards

There's one box per tracked student, and they're kept in a stable order so a card
never jumps around when its own data updates. Each card shows four things:

| Element | What it shows |
|---|---|
| **Strategy state** | the current HMM state: Iterator, Explorer, or Stuck |
| **Strategy sparkline** | the per-run HMM state sequence over time |
| **Episode sparkline** | the segmented code / run / reset timeline |
| **Counts** | run and event totals for the session |

### What the strategy states mean

| State | Label | How to read it |
|---|---|---|
| 0 | Iterator | steady, incremental edits between runs |
| 1 | Explorer | bigger structural changes, trying new approaches |
| 2 | Stuck | wheel-spinning, not much productive change |

## Who-needs-help column

The column on the right is the live intervention feed. It shows every alert the
daemon has fired and hasn't yet seen resolved or acknowledged.

| Trigger | Colour | Fires when |
|---|---|---|
| **Wheel-spinning** | red `⟳` | the HMM puts the student in the *stuck* state |
| **Inactive** | amber `⏸` | no events for 5 minutes or more |
| **Big rewrite** | purple `✎` | a single run's `change_score` hits 0.5 or higher |

Each row shows the student ID, the trigger label and its value (something like `3
re-runs` for wheel-spin, `7m 12s` for inactive, `change 0.71` for a big rewrite),
and how long ago it fired. Click a row to jump into that student's card, or click
**ack** to dismiss the alert without leaving the column.

!!! note "Re-alert"
    Acking a sustained trigger (wheel-spin or inactive) doesn't silence it forever.
    If the condition keeps holding for another 10 minutes, the daemon closes the
    acked row and opens a fresh one, so a student who never actually got unstuck
    comes back to the feed.

## Pause / resume polling

The top bar has a **⏸ Pause polling** toggle. Pausing tells the daemon to stop
hitting the production server completely. It makes zero requests to prod while
paused, keeps showing the last data it pulled, and picks back up within about a
second of you clicking **▶ Resume polling**. While it's off, the status dot turns
amber and a "polling paused" label shows up next to the title.

!!! tip
    Use this between sessions. The daemon polls production the whole time it's
    running, even during quiet stretches, which is a constant load on prod. Pausing
    when no class is active gives prod room to recover, which really matters if it's
    on a CPU-credit (burstable) instance. The toggle is shared, so every open
    dashboard sees the same state.

The daemon process keeps running while paused. Pausing only stops the polling, not
the daemon itself.

## Drill-down

Click any card to open the full detail:

- The **playground prompt**, which is their current code described in plain
  language for an LLM.
- Full-size **episode** and **strategy** timelines.

It all comes from the same payload the card already has, so the modal opens
instantly.

## Export

The **⬇ Export** button writes a CSV snapshot of every table (raw events,
materialized state, triggers, roster) to `exports/export_<timestamp>/`. It's
read-only, so the database is never touched and you can run it any time. A success
dialog tells you where it landed.

## Reset

The **↺ Reset** button clears all the locally-stored events, episodes, strategy
state, and flags, and tells the daemon to drop its in-memory workers so the board
starts fresh from new activity.

!!! warning "Reset has no automatic backup"
    Hit **Export** first if you want a CSV copy. Reset is destructive locally, and
    once it returns there's no undo.

!!! info
    Reset is local only. Production is never touched. The raw event cursor stays put,
    so the board rebuilds only from activity that arrives after the reset, and
    tracked students stay tracked.

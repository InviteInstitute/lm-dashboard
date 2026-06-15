---
description: Student cards, the who-needs-help column, drill-down detail, and the reset button.
---

# Using the dashboard

The dashboard is a single screen at
[http://localhost:3000](http://localhost:3000). Everything on it derives from one
polled payload, so the whole view stays in sync.

## Track a student

Type a student ID into **Track a student**. The daemon backfills their recent
history, materializes their state, and their card appears within a tick or two.
Removing a student stops tracking them and deletes their local data.

## Student cards

One box per tracked student, in a **stable order** so a card never jumps when its
own data updates. Each card shows:

<div class="grid cards" markdown>

-   :material-brain:{ .lg .middle } **Strategy state**

    ---

    The current HMM state: **Iterator**, **Explorer**, or **Stuck**.

-   :material-chart-line:{ .lg .middle } **Strategy sparkline**

    ---

    The per-run HMM state sequence over time.

-   :material-layers-triple:{ .lg .middle } **Episode sparkline**

    ---

    The segmented code / run / reset timeline.

-   :material-pound:{ .lg .middle } **Counts**

    ---

    Run and event totals for the session.

</div>

### What the strategy states mean

| State | Label | Reading |
|---|---|---|
| 0 | Iterator | steady, incremental edits between runs |
| 1 | Explorer | larger structural changes, trying new approaches |
| 2 | Stuck | wheel-spinning, little productive change |

## Who-needs-help column

The right-side column is the live intervention feed. It surfaces every alert the
daemon has fired and not yet seen resolved or acknowledged.

| Trigger | Colour | Fires when |
|---|---|---|
| **Wheel-spinning** | red `⟳` | HMM places the student in the *stuck* state |
| **Inactive** | amber `⏸` | no events for ≥ 5 minutes |
| **Big rewrite** | purple `✎` | a single run's `change_score` ≥ 0.5 |

Each row shows the student ID, the trigger label and value (for example
`3 re-runs` for wheel-spin, `7m 12s` for inactive, `change 0.71` for big
rewrite), and how long ago it fired. Click a row to drill into that student's
card, or click **ack** to dismiss the alert without leaving the column.

!!! note "Re-alert"
    Acknowledging a sustained trigger (wheel-spin or inactive) does not silence
    it forever. If the condition keeps holding for another 10 minutes the
    daemon closes the acked row and opens a fresh one, so a student who never
    actually got unstuck re-surfaces in the feed.

## Pause / resume polling

The top bar has a **⏸ Pause polling** toggle. Pausing tells the daemon to stop
hitting the production server entirely — it makes **zero requests to prod** while
paused, keeps showing the last data it fetched, and resumes within about a second
of clicking **▶ Resume polling**. The status dot turns amber and a "polling
paused" label appears while it's off.

!!! tip
    Use this between sessions. The daemon polls production continuously while
    running (even during quiet stretches), which keeps a constant load on prod.
    Pausing when no class is active lets prod recover — important if it runs on a
    CPU-credit (burstable) instance. The toggle is shared, so every open
    dashboard reflects the same state.

The daemon process keeps running while paused; pausing only stops the prod
polling, not the daemon itself.

## Drill-down

Click any card to open the full detail:

- The **playground prompt**: their current code described in natural language for
  an LLM.
- Full-size **episode** and **strategy** timelines.

All of this comes from the same payload the card already has, so the modal opens
instantly.

## Export

The **⬇ Export** button writes a CSV snapshot of every table — raw events,
materialized state, triggers, roster — to `exports/export_<timestamp>/`. It is
**read-only**: the database is never modified, so it is safe to run at any time.
A success dialog reports the destination directory.

## Reset

The **↺ Reset** button in the top bar clears all locally-stored events,
episodes, strategy state, and flags, and tells the daemon to drop its in-memory
workers so the board starts fresh from new activity.

!!! warning "Reset has no automatic backup"
    Click **Export** first if you want to keep a CSV copy. Reset is destructive
    locally; once it returns there is no undo.

!!! info
    Reset is **local only** — production is never touched. The raw event cursor
    is left intact, so the board rebuilds only from activity that arrives after
    the reset. Tracked students stay tracked.

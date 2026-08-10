---
description: Student cards, the who-needs-help column, drill-down detail, and the reset button.
---

# Using The Dashboard

The dashboard is a single screen. The first time you open it your **browser prompts
for a username and password** - that's the login. Each browser then gets its **own
isolated board**: your roster, notes, and picks are yours, separate from anyone else
signed in with the same credentials.

It holds one live stream to the API and refetches only what changed, so the whole
view stays in sync with itself and updates land in about a quarter second. If the
stream ever drops, it silently falls back to polling until it reconnects. You never
have to think about it.

## Track A Student

Type a student ID into **Track a student**. The daemon backfills their recent
history, materializes their state, and their card shows up within a tick or two.
Removing a student takes them off *your* board. Their shared mirror is only purged
once no board is tracking them any more.

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
Marking a student absent dims their card and drops it down. Marking them picked records
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
fired, plus a faint **last:** line with the student's previous trigger and its
wall-clock time (for example `last: Wheel-spinning · 10:24 AM (12m ago)`), so a first
flag reads differently from the fifth in ten minutes. Click a row to open that
student's detail, hit the **✕** to dismiss the alert, or use **Notes** to jot an
observation right against the alert.

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

## Identity Switches

Student handles are folded case-insensitively, so `cobra3` and `Cobra3` are one
student (the board shows whichever casing arrived most recently). When a tracked
handle flips casing or turns up under a new class code, an amber **toast** pops in the
top-right corner and the switch lands in the **Identity Switches** feed under the
alerts. That's usually the signal that one person or a shared device is active in two
places, which is worth knowing before you read too much into their timeline. Dismiss
a switch with its **✕** once you've seen it.

## When A Click Fails To Save

Your inputs (presence, picked, notes, dismissals, roster edits) are the one thing the
system can't recompute, so they never fail silently. Every click applies instantly,
retries quietly if the write hiccups, and if it still can't land you get a sticky
**red "NOT saved" toast** naming the action. The input itself is parked verbatim in
the outbox (on the server, or in the browser until the server is reachable again), so
nothing you typed or clicked is ever lost. Red toasts stay until you dismiss them. If
you see one, the outbox has the details.

## Pause / Resume Polling

The top bar has a **⏸ Pause polling** toggle. Pausing tells the daemon to stop hitting
the production server completely. It makes zero requests to prod while paused, keeps
showing the last data it pulled, and picks back up within about a second of you
clicking **▶ Resume polling**. While it's off, the status dot turns amber and a
"Daemon Paused" label shows up next to the title.

!!! tip
    Use this between sessions. While your board is being watched the daemon polls
    production for its students, which is load on prod. Pausing when no class is active
    gives prod room to recover, which really matters if it's on a CPU-credit
    (burstable) instance. The toggle is **per board** - it affects your board's
    students, not anyone else's.

The daemon process keeps running while paused. Pausing only stops the polling, not the
daemon itself.

## Drill-Down

Click any card to open the full detail:

- The **Program**, their latest blocks rendered as a readable listing with every
  parameter spelled out, including the numbers: `drive for forward, mm, amount 200`,
  and nested conditions inline like `if (not (object distance < 200))`.
- The **playground prompt**, the same code described in plain language for an LLM.
- Full-size **run** and **episode** timelines.
- The **trigger history grid**: every trigger fired for this student this session
  (Time, Trigger, Value, Status), newest first, including resolved and dismissed
  rows, so you can see the pattern behind the current alert.
- The complete **notes and observations** log for that student, with a box to add
  more.

The detail view fetches its own per-student payload on open and keeps it refreshed
while the modal is up, following the same live stream as the rest of the board.

## Export

The **⬇ Export** button downloads a **zip of CSV snapshots** of your board (its
roster, notes, and picks, plus the shared events, materialized state, and triggers for
the students it tracks) straight to your computer. It's built in memory and is
read-only, so the database is never touched and nothing is written to the server - you
can run it any time. The file is named `lm-dashboard_export_<timestamp>.zip`.

## Reset

The **↺ Reset** button clears **your board's** researcher data for a fresh session:
its notes, the picked toggles and pick history, and its trigger dismissals. Your
roster and presence stay, and the shared per-student mirror is left intact (other
boards depend on it, and your board just re-derives its view from it).

!!! info
    Reset writes a CSV backup of your board (notes and picks included) to
    `exports/reset_<timestamp>/` on the server before it wipes, so nothing is lost, and
    the failed-write outbox is deliberately spared. Production is never touched.

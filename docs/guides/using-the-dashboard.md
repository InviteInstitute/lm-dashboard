---
description: Student cards, the who-needs-help column, the student sheet, and the reset button.
---

# Using The Dashboard

The dashboard is a single screen. There is no login: the first time you open it, the
browser passes a Cloudflare Turnstile check that keeps bots off the API, and it
remembers that for 12 hours. Each browser gets its **own isolated board**, so your
roster, notes and picks are separate from everyone else's.

It holds one live stream to the API and refetches only what changed, so the whole
view stays in sync with itself and updates land in about a quarter second. If the
stream ever drops, it silently falls back to polling until it reconnects. You never
have to think about it.

## VEXcode VR Or ZANY

A board listens to one source, picked in **Listening to** beside the Students heading:

- **VEXcode VR**, the classroom logs Reflecks collects, as always.
- **ZANY (class code)**, the logs ZANY sends to ATLAS-invite (zany.inviteai.org) for one study. ATLAS
  keeps only what a participant's consent allows, and lm-dashboard reads them from ATLAS's store
  read-only, within about a second of ATLAS keeping them.

ZANY's logs are for the research team. Picking ZANY the first time asks for the research login,
the same one as ATLAS's research pages; ATLAS checks it, and the browser stays unlocked for 12
hours. Five wrong tries lock it for ten minutes.

On a ZANY board, track participants by the IDs they typed (R01, R02), or **Track everyone in**
the study. Cards show those IDs. When ATLAS deletes some of a participant's records (a researcher
deleted or reset them), lm-dashboard drops what it made from them at once and rebuilds it from what
is left. Each board keeps its own roster per source, so switching back to Reflecks shows the
Reflecks students again.

## Track A Student

Type a student ID into **Track student IDs**, beside the Students heading. The daemon backfills their recent
history, materializes their state, and their card shows up within a tick or two.
Removing a student takes them off *your* board. Their shared mirror is only purged
once no board is tracking them any more.

## Student Cards

There's one card per tracked student. Present students come first, then absent
ones, each group in order of student ID, so a card never jumps around while you
watch it. Each card shows:

| Element | What It Shows |
|---|---|
| **Status badge** | the student's headline state, derived from their active triggers (or **OK** when none are firing) |
| **Run track** | the last ten runs, one tile each, coloured by that run's edit distance |
| **Episode track** | the last ten episodes (code, run, reset), with the pauses between them |
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

The column on the right is the live intervention feed. It shows the alerts the daemon
has fired for present students on your board, until you dismiss them. An alert that
resolves on its own stays for seven more minutes, so it doesn't vanish the moment a
student recovers. There are five triggers:

| Trigger | Fires When | Example value |
|---|---|---|
| **Wheel-spinning** | six or more identical re-runs in a row (`edit_distance == 0`) | `6 identical reruns` |
| **Resilience** | a real edit right after four or more identical re-runs | `recovered after 5 reruns` |
| **Inactive** | no events for four minutes (240s) or more | `idle 7m` |
| **Explorer** | a single run changes 13 or more blocks | `changed 21` |
| **Step-by-Step** | a streak of steady edits (`edit_distance >= 1`): six runs, or fewer on some playgrounds (five on Coral Reef Rescue, three on Rover Rescue) | `6 steady edits` |

Each row shows the student ID, the trigger label and its value, and how long the
alert has been active, plus a quiet line with the student's previous trigger and its
wall-clock time (for example `Before this: Wheel-spinning at 10:24 AM (12m ago)`), so a
first flag reads differently from the fifth in ten minutes. Click a row to open that
student's sheet, **✕** to dismiss the alert, **Mark Picked** to record an interview
pick that remembers which alert prompted it, or **Add Note** to write an observation
tied to the alert.

!!! note "Wheel-spinning and Resilience are a pair"
    They read the same streak from opposite ends: wheel-spinning fires while a student
    re-runs identical code, and resilience fires the moment they finally make a real
    edit. On a run of six zeros followed by an edit you'll see both, which is by design.

!!! note "Re-Alert"
    Acking the **inactive** alert doesn't silence it forever. If the student stays idle
    for another 10 minutes, the daemon closes the acked row and opens a fresh one, so
    someone who never came back keeps resurfacing in the feed.

You can also turn whole trigger types on or off from **Triggers** (the sliders icon) in
the header, which opens a panel with a switch for each type. Switching one off tells
the daemon to stop firing it and to clear its open alerts. Unlike everything else in
this guide, this switch is shared by every board, not kept per board.

## Identity Switches

Student handles are folded case-insensitively, so `cobra3` and `Cobra3` are one
student (the board shows whichever casing arrived most recently). When a tracked
handle flips casing or turns up under a new class code, an amber **toast** pops up in
the bottom-right corner and the switch lands in the **Identity Switches** feed under the
alerts. Switches from before you opened the board are in the feed without a toast. That's usually the signal that one person or a shared device is active in two
places, which is worth knowing before you read too much into their timeline. Dismiss
a switch with its **✕** once you've seen it.

## When A Click Fails To Save

Your inputs (presence, picked, notes, dismissals, roster edits) are the one thing the
system can't recompute, so they never fail silently. Every click applies instantly,
retries quietly if the write hiccups, and if it still can't land you get a sticky
**red "Not saved" toast** naming the action. The input itself is parked verbatim in
the outbox (on the server, or in the browser until the server is reachable again), so
nothing you typed or clicked is ever lost. Red toasts stay until you dismiss them. If
you see one, the outbox has the details.

## Pause / Resume Polling

The header has a **Pause polling** button (the pause icon). Pausing tells the daemon to stop hitting
the production server completely. It makes zero requests to prod while paused, keeps
showing the last data it pulled, and picks back up within about a second of you
clicking **Resume polling** (the play icon). While it's off, the green **Live** tag next to
the title turns grey and reads **Polling paused**.

!!! tip
    Use this between sessions. While your board is being watched the daemon polls
    production for its students, which is load on prod. Pausing when no class is active
    gives prod room to recover, which really matters if it's on a CPU-credit
    (burstable) instance. The toggle is **per board** - it affects your board's
    students, not anyone else's.

The daemon process keeps running while paused. Pausing only stops the polling, not the
daemon itself.

## Student Sheet

Click any card or alert to open that student's sheet, which slides in over the right of
the board so the rest of the class stays in view. On the left is the evidence:

- Full-size **episode** and **run** timelines, every one since the last reset.
- The **Latest program**, with a switch between two renderings of the same blocks:
  - **Readable**: every block with its parameters spelled out, including the
    numbers: `drive for forward, mm, amount 200`, and nested conditions inline
    like `if (not (object distance < 200))`.
  - **LLM prompt**: the same program flattened into the compact text given to an
    LLM as context.
- **Goal evidence**, for Castle Crashers runs only: a table of where each goal's
  claim landed on every run, then, for the run you pick, each goal's reading on its
  ladder with the indicators, rung changes and sensor test worlds behind it, and the
  provisional execution rubric. Every reading carries its uncertainty flags, and a
  goal with no evidence says so rather than showing a fake rung. It is evidence for
  you to weigh, not a score.

On the right is your own record of the student:

- Your **notes**, newest first, with a box to add more (Ctrl+Enter saves).
- The **trigger history**: every trigger this student has had since the last reset,
  newest first, with its time, value and whether it is active, resolved or
  dismissed, so you can see the pattern behind the current alert.

The sheet keeps itself current while it is open, following the same live stream as
the rest of the board. Escape, the **✕** or a click outside it closes it.

## Export

**Export** (the download icon in the header) downloads a **zip of CSV snapshots** of your board (its
roster, notes, and picks, plus the shared events, materialized state, and triggers for
the students it tracks) straight to your computer. It's built in memory and is
read-only, so the database is never touched and nothing is written to the server - you
can run it any time. The file is named `lm-dashboard_export_<timestamp>.zip`.

## Reset

**Reset** (the circular arrow in the header) starts **your board** fresh, after you
confirm it in a dialog. Every part of each student tile
then shows only what happens after the reset: the runs and episodes, the goal
evidence, the alerts, the trigger history and the switches. It also clears your
board's notes, the picked toggles and pick history, and its trigger dismissals. Your
roster and presence stay, and the shared per-student data is left intact: other
boards still see it, and your board simply stops showing what came before.

Run numbers don't restart at a reset, so a run keeps the same number on the
activity strip, in goal evidence and in alerts.

!!! info
    Reset writes a CSV backup of your board (notes and picks included) to
    `exports/reset_<timestamp>/` on the server before it wipes, so nothing is lost, and
    the failed-write outbox is deliberately spared. Production is never touched.

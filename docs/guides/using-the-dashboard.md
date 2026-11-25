---
description: Student cards, the Needs Intervention column, the student sheet, export and reset.
---

# Using The Dashboard

The dashboard is one screen. There is no login. The first time you open it, the browser passes a
Cloudflare Turnstile check that keeps bots off the API, and it remembers that for 12 hours. Each
browser gets its own board, so your roster, notes and picks are separate from everyone else's.

The board holds one live stream to the API and refetches only what changed, so an update shows up
in about a quarter second. If the stream drops, the board polls until it reconnects, and you won't
notice the difference.

## VEXcode VR Or ZANY

A board listens to one source, which you pick in **Listening to** beside the Students heading.

- **VEXcode VR** is the classroom logs that Reflecks collects.
- **ZANY (class code)** is the logs ZANY sends to ATLAS-invite (zany.inviteai.org) for one study.
  ATLAS keeps only what a participant's consent allows.

ZANY's logs are for the research team. The first time you pick ZANY, the board asks for the
research login, the same one as ATLAS's research pages. The browser then stays unlocked for 12
hours. Five wrong tries lock it for ten minutes.

On a ZANY board, you track participants by the IDs they typed (R01, R02), or click **Track
everyone in** to add the whole study. Cards show those IDs. When ATLAS deletes some of a
participant's records, the dashboard drops what it made from them and rebuilds it from what is
left. Each board keeps its own roster per source, so switching back to VEXcode VR shows your
Reflecks students again. [Sources](../concepts/sources.md) has the details.

## Track A Student

Type a student ID into **Track student IDs**, beside the Students heading. The daemon copies their
activity since it started, works out their state, and their card shows up within a second or two.

Removing a student takes them off your board only. Their shared data is deleted once no board
tracks them.

## Student Cards

There is one card per tracked student. Present students come first, then absent ones, and each
group is sorted by student ID, so a card never jumps around while you watch it.

| Part | What it shows |
|---|---|
| Status | the student's headline, from their active alerts, or **OK** when none are firing |
| Run track | the last ten runs, one tile each, colored by how much the code changed |
| Episode track | the last ten episodes (code, run, reset), with the pauses between them |
| Counts | runs and events since the last reset |

Each card also has **Present** and **Picked** toggles for interviews. Marking a student absent dims
their card and moves it down. Marking them picked records that you interviewed them this session,
with the time.

### Reading The Run Track

Each run is colored by its edit distance from the run before it, which is the number of blocks that
changed.

| Color | Edit distance | What it means |
|---|---|---|
| grey | `0` | the same code ran again |
| blue | 1 to 12 | an edit |
| purple | 13 or more | a big change |

There is no model behind the colors. The color is the count of changed blocks, and the five
triggers are rules over that sequence of counts.

## Needs Intervention

The column on the right is the live alert feed. It shows the alerts for present students on your
board until you dismiss them. An alert that resolves on its own stays for seven more minutes, so it
doesn't vanish the moment a student recovers.

| Trigger | Fires when | Example value |
|---|---|---|
| Wheel-spinning | the same code runs six times in a row | `6 identical reruns` |
| Resilience | a real edit comes right after four or more identical re-runs | `recovered after 5 reruns` |
| Inactive | no events for four minutes | `idle 7m` |
| Explorer | one run changes 13 or more blocks | `changed 21` |
| Step-by-Step | a steady run of edits, six on most playgrounds, five on Coral Reef Rescue and three on Rover Rescue | `6 steady edits` |

Each alert shows the student, the trigger and its value, and how long it has been active. A quieter
line under it names the student's previous alert and when it was, like `Before this: Wheel-spinning
at 10:24 AM (12m ago)`, so a first alert reads differently from a fifth in ten minutes.

Click an alert to open the student's sheet. **✕** dismisses it. **Mark Picked** records an
interview pick and remembers which alert prompted it, and **Add Note** writes an observation tied
to the alert.

!!! note "Wheel-spinning and Resilience come in pairs"
    They read the same streak from opposite ends. Wheel-spinning fires while a student re-runs the
    same code, and Resilience fires when they finally change it. Six zeros followed by an edit
    shows both, and that is on purpose.

!!! note "Inactive comes back"
    Dismissing an Inactive alert doesn't silence it for good. If the student is still idle 10
    minutes after the alert started, a new one opens, so a student who never came back keeps
    showing up.

**Triggers** (the sliders icon in the header) opens a panel with a switch for each type. Turning one
off hides it on your board only. The daemon keeps checking every type, so turning one back on
brings back its alerts that are still current.

## Identity Switches

Student IDs ignore case, so `cobra3` and `Cobra3` are one student, and the board shows whichever
casing came last. When a tracked ID changes casing or turns up under a new class code, an amber
toast pops up in the bottom right, and the switch goes into the **Identity Switches** list under the
alerts. Switches from before you opened the board are in the list without a toast.

A switch often means one person is on two devices, or one device is shared. That is worth knowing
before you read too much into a timeline. Dismiss a switch with its **✕** once you've seen it.

## When A Click Doesn't Save

Your inputs (presence, picks, notes, dismissals and roster changes) are the one thing the system
can't rebuild, so they never fail quietly. A click shows at once and retries if the write fails. If
it still can't save, a red **Not saved** toast names the action, and the input is kept word for
word in the outbox, on the server or in your browser until the server answers again. Red toasts
stay until you dismiss them.

## Pause Polling

**Pause polling** (the pause icon in the header) stops the daemon from asking production for your
board's students. It keeps showing the data it already has. **Resume polling** (the play icon)
starts it again within about a second and fills in what happened during the pause. While polling
is paused, the green **Live** tag by the title turns grey and reads **Polling paused**.

!!! tip "Pause between sessions"
    While your board is open, the daemon polls production for its students, and that is load on
    production. Pausing when no class is running gives production a rest. The switch is per
    board, so it only affects your students.

The daemon keeps running while you're paused. Only the polling stops.

## Student Sheet

Click a card or an alert to open that student's sheet. It slides in over the right of the board, so
the rest of the class stays in view.

On the left is the evidence.

- Full-size episode and run timelines, every one since the last reset.
- The **Latest Program**, with a switch between two views of the same blocks. **Readable** spells
  out every block and its values, like `drive for forward, mm, amount 200`, with nested conditions
  inline, like `if (not (object distance < 200))`. **LLM prompt** is the same program in the
  compact text an LLM gets as context.
- **Goal evidence**, for Castle Crashers runs only. A table shows where each goal's claim landed on
  every run. For the run you pick, it shows each goal's reading on its ladder with the indicators,
  the rung changes and the sensor test worlds behind it, and the provisional execution rubric.
  Every reading shows its uncertainty, and a goal with no evidence says so instead of showing a
  made-up rung. It is evidence for you to weigh, not a score.

On the right is your own record.

- Your **notes**, newest first, with a box to add one. Ctrl+Enter saves.
- The **trigger history**, every alert this student had since the last reset, newest first, with
  its time, value and whether it is active, resolved or dismissed.

The sheet updates itself while it is open. Escape, the **✕** or a click outside closes it.

## Export

**Export** (the download icon) saves a zip of CSV files to your computer. It holds your board's
roster, notes, picks and dismissals, plus the events, state, alerts, goal evidence and identity
switches of the students you track. It only reads, so you can run it any time. The file is named
`lm-dashboard_export_<timestamp>.zip`.

## Reset

**Reset** (the circular arrow) starts your board fresh after you confirm it in a dialog. Every part
of each card then shows only what happens after the reset, including runs, episodes, goal evidence,
alerts, trigger history and switches. It also clears your board's notes, picks and pick history, and
its dismissals.

Your roster and presence stay. The shared student data stays too, so other boards still see it, and
your board simply stops showing what came before. Run numbers don't restart, so a run keeps its
number on the run track, in goal evidence and in alerts.

!!! info
    Reset first writes a CSV backup of your board, notes and picks included, to
    `exports/reset_<timestamp>/` on the server. The outbox is left alone. Production is never
    touched.

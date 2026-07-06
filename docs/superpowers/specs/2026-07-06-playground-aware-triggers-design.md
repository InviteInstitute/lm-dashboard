---
description: Make the run-based intervention triggers playground-aware, so a student who switches VEX playgrounds is analyzed per playground with a hard reset at each switch.
---

# Playground-Aware Run Analysis

Status: Draft, 2026-07-06. Internal design spec (not part of the published guide).

## Problem

The five intervention triggers all read one flat sequence of per-run edit distances,
which assumes a student stays in a single VEX playground for the whole session. Students
do switch playgrounds, and that breaks the analysis two ways:

1. The edit distance across a switch compares two unrelated programs (say `ArtCanvas`
   code against `RoverRescue` code), so it comes out as a large, meaningless number.
   That noise can fire the Explorer trigger and skew the others.
2. `ITERATIVE_THRESHOLDS` (the per-playground Step-by-Step thresholds) is defined in
   `app/constants.py` but never used, because nothing attributes a run to a playground.

The playground name is already in the telemetry: every run's `project` JSON carries a
`playground` field (confirmed in the live data, with values like `ArtCanvas`,
`CastleCrasherPlus`, `RoverRescue`), and the worker already parses that same project JSON
to build the playground prompt.

## Requirements

- Attribute each run to the playground it happened in (the `playground` field inside the
  run's project JSON).
- Split a student's run sequence into contiguous same-playground stretches.
- At each stretch boundary the first run starts fresh: its `edit_distance` is `null`,
  exactly like the very first run, so no cross-playground diff is ever computed.
- Every run-based trigger (Wheel-spinning, Resilience, Explorer, Step-by-Step) counts
  only within the current stretch. All counters reset at each boundary.
- Step-by-Step uses the current stretch's playground threshold:
  `ITERATIVE_THRESHOLDS.get(playground, ITERATIVE_DEFAULT_THRESHOLD)`.
- Returning to a previously visited playground starts a brand-new stretch. Runs from the
  earlier visit do not carry over into the new count.
- Inactive is unaffected. It is time-based, evaluated by the per-tick sweep, not from the
  run sequence.

## Design

All changes live in the daemon. No database schema, read API, or frontend change.

### 1. Attribute Runs and Reset the Baseline: `compute_run_edit_distances`

`app/runs/run_sequence.py` already walks the runProject events and parses each project's
block tree to compute the integer edit distance against the previous run. In the same
pass it also reads the sibling `playground` field. The one behavioral change: when a
run's playground differs from the previous run's, that run is treated as a fresh baseline,
so its `edit_distance` is `null` (the same value the very first run already gets). Each
run entry gains a `playground` key. This is additive to the persisted `runs` payload; the
read API and frontend ignore the extra key, and it sets up the deferred visibility work
and shows up in the CSV export.

### 2. Per-Stretch Trigger Detection: `workers.py` and `triggers.py`

`detect_run_triggers` stays a pure function over a single stretch's edit-distance list.
The worker groups the runs into contiguous same-playground stretches and calls
`detect_run_triggers` once per stretch, passing that stretch's threshold
(`ITERATIVE_THRESHOLDS.get(playground, ITERATIVE_DEFAULT_THRESHOLD)`) and offsetting the
returned run indices back to global indices.

Because `detect_run_triggers` starts every call with fresh counters (the zero streak, the
iterative count, the re-arm flags), calling it per stretch gives the hard reset for free.
Jumping back to an earlier playground is simply another fresh call. Dedupe by run index is
unchanged, since the offset keeps indices global, and the fired-index sets seeded from the
database on rehydrate still prevent repeats.

Keeping the playground logic in the segmentation (not inside `detect_run_triggers`) keeps
the pure function simple and easy to test on its own.

### 3. Edge Cases

- A run whose project JSON has no `playground`, or is unparseable, is treated as a
  continuation of the current stretch (carry the last known playground, no reset), so one
  malformed event cannot spuriously chop a stretch.
- A session that never switches playground behaves exactly as it does today, only now with
  the correct per-playground threshold applied.
- The very first run overall keeps its `null` edit distance as before.

## Out of Scope

Surfacing the playground on the dashboard (marking switches on the run track, labeling the
current challenge) beyond the additive per-run `playground` field. That is a clean
follow-on and is deliberately deferred so this change stays contained to the daemon.

## Testing

- `run_sequence`: `edit_distance` becomes `null` at a playground switch, and each run is
  tagged with its playground. A missing playground field does not cause a reset.
- `triggers` / segmentation: `CastleCrasherPlus` fires Step-by-Step at 6 while
  `RoverRescue` fires at 3; a switch mid-stream resets the count; a jump back to an earlier
  playground does not resume the old count; and a cross-playground boundary no longer fires
  Explorer off a garbage diff.
- An unlisted playground (for example `ArtCanvas`) falls back to the default threshold of 6
  and still fires normally.

## Decisions and Assumptions

- `ITERATIVE_THRESHOLDS` had a mis-keyed name: `CoralReefCleanup` does not appear in the
  telemetry. The real playground names in the logs are `CastleCrasherPlus`,
  `CoralReefRescue`, and `RoverRescue` (confirmed by the researcher). The dict is corrected
  to `{"CastleCrasherPlus": 6, "CoralReefRescue": 5, "RoverRescue": 3}`. Because an exact
  string match is required and a miss falls back silently to the default, the wrong key
  would have quietly used 6 instead of 5 for the reef challenge.
- The segmentation reads each run's playground with `.get("playground")`, defaulting to
  `None`, so runs built without the field (older cached rows, test fixtures) behave as a
  single default-threshold stretch rather than erroring.
- The hard reset applies to all run-based triggers, not only Step-by-Step (confirmed).
  Why: the cross-playground edit distance is meaningless for every trigger, not just the
  threshold-based one.
- Each contiguous visit is independent, with no cumulative per-playground memory across
  visits (confirmed). Returning to a playground starts fresh.
- An unlisted playground falls back to `ITERATIVE_DEFAULT_THRESHOLD` (6) and the trigger
  still fires (confirmed).
- A missing or unparseable `playground` field is treated as a continuation, not a switch
  (assumption, to avoid spurious stretch splits from a single bad event).
- The playground is read from the run's own project JSON, reusing the parse already done
  for the block tree.
- Segmentation lives in the worker/caller; `detect_run_triggers` remains a pure
  single-stretch function.
- No schema, API, or frontend change. The per-run `playground` is added to the `runs`
  payload additively.

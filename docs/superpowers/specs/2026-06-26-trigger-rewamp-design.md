# Trigger Rewamp: HMM → Edit-Distance Rules

**Date:** 2026-06-26
**Status:** Design, pending implementation
**Source:** "Vex summer data collection trigger" deck (Hyeongjo) + design discussion

## Goal

Replace the black-box CategoricalHMM strategy model with five deterministic,
glass-box triggers computed directly from each run's APTED **edit_distance**. The
HMM and its supporting code (model file, hmmlearn/numpy/sklearn/joblib, the
probabilistic state layer) come out entirely. The per-run code-diff signal stays,
but as the raw integer tree-edit distance, not the normalized change_score.

Motivation (from the deck): the code change score is more objective and directly
interpretable as student intent, and the thresholds are chosen from the summer
data distributions.

## The Signal: `edit_distance`

Today the worker computes a normalized `change_score = dist / (max_size + 10)` and
discards the raw `dist`. The new triggers are defined on that raw `dist` (an
integer), so we expose it and delete the normalization.

### Cost-model fix (required for the thresholds to mean anything)

The deck's thresholds (`>1`, `>=13`) assume Hyeongjo's APTED cost config:

```
block_delete_cost = 1.0
block_insert_cost = 1.0
edge_delete_cost  = 0      # edges are free to add/remove...
edge_insert_cost  = 0      # ...so adding a block (block+edge) scores 1, not 2
field_change_cost = 1.0
type_change_cost  = 1.0
edge_change_cost  = 1.0
```

Our current `BlocklyConfig` differs in two ways that change every non-zero
distance: `field_change_cost = 0.3` (must become `1.0`), and edge insert/delete
charged the flat `1.0` (must become `0`). Because our AST inserts an explicit
edge node between every parent and child, charging edge insert/delete double-counts
every structural edit. With edge cost 0 and all others 1.0, `edit_distance` is
integer-valued, matching the deck's histogram.

**`BlocklyConfig` becomes edge-aware:**

- `delete(node)` → `EDGE_DELETE_COST` (0) if `node.node_type == "__edge__"` else `BLOCK_DELETE_COST` (1.0)
- `insert(node)` → `EDGE_INSERT_COST` (0) if edge node else `BLOCK_INSERT_COST` (1.0)
- `rename(a, b)` → 0 if names equal; `EDGE_CHANGE_COST` if either is an edge node (and names differ); `FIELD_CHANGE_COST` if same `node_type`; else `TYPE_CHANGE_COST`

`apted_similarity` returns the raw distance (`APTED(...).compute_edit_distance()`);
the `change_score` normalization, `SIMILARITY_SMOOTHING`, and `_count_tree_nodes`
are removed. The XML-pair memo cache stays (renamed to cache distances).

## The Five Triggers

All thresholds live in `constants.py`, named exactly as shown so the "Fires when"
rule and its "Threshold" use the same name. `edit_distance` is the whole number
measuring how much the code changed since the previous run (`0` = identical).

| Trigger | Kind | Fires when | Threshold | Cooldown / reset |
|---|---|---|---|---|
| **wheel_spin** (Stuck) | momentary, per-run | a run of consecutive `edit_distance == 0` reaches `WHEEL_SPIN_ZERO_RUNS` | `WHEEL_SPIN_ZERO_RUNS = 6` (6 or more) | silent until an `edit_distance > 0` run |
| **resilience** | momentary, per-run | an `edit_distance > 0` run lands right after `RESILIENCE_ZERO_RUNS` or more trailing zeros | `RESILIENCE_ZERO_RUNS = 4` | fires at the breakout run |
| **inactive** (Idle) | sustained, sweep | no event for more than `INACTIVE_TRIGGER_SECONDS` seconds (existing any-event idle) | `INACTIVE_TRIGGER_SECONDS = 240` | resolves when a new event arrives |
| **explorer** | momentary, per-run | a single run's `edit_distance >= EXPLORER_EDIT_DISTANCE` | `EXPLORER_EDIT_DISTANCE = 13` | one alert per qualifying run (dedupe by index) |
| **iterative** (Step-by-Step) | momentary + counter | the count of runs with `edit_distance > ITERATIVE_EDIT_MIN` reaches `ITERATIVE_DEFAULT_THRESHOLD` | `ITERATIVE_DEFAULT_THRESHOLD = 6`, `ITERATIVE_EDIT_MIN = 1` | silent after firing until an `edit_distance == 0` run, which also zeroes the count |

### Notes per trigger

- **wheel_spin** fires at the run where the trailing zero-streak first reaches 6
  ("6 or more"). It then stays silent (cooldown) until an `ed > 0` run re-arms it;
  a later 6-zero streak fires again.
- **resilience** is the "recovered after being stuck" signal: an edit emerging from
  >= 4 consecutive no-change runs. It **fires and logs independently** of wheel_spin.
  The only priority rule is for the single headline status (below).
- **inactive** keeps today's implementation unchanged (idle measured from
  `last_event_time` over any event) and is simply retuned to 240s. It remains a
  sustained trigger evaluated in the sweep; the segmenter's `PAUSE_THRESHOLD_S = 300`
  is untouched.
- **explorer** absorbs the old `big_change`. Fires once per qualifying run, deduped
  by run index. No cooldown.
- **iterative** counts runs with `edit_distance > 1` across the whole session (no
  reset on activity switch). When the count reaches the threshold it fires once; it
  then stays silent until an `edit_distance == 0` run, which clears the cooldown and
  resets the count to 0 (the burst boundary). An `edit_distance == 1` is a trivial
  change: it neither counts nor resets.

### Per-playground thresholds (reference only, not wired)

The deck specifies per-activity Iterative thresholds, but the activity name is not
in the telemetry, so the code uses `ITERATIVE_DEFAULT_THRESHOLD = 6` for everyone.
The full table is pasted into `constants.py` as an editable reference for manual
tuning later:

```python
# Reference only -- not used until the playground name is available in telemetry.
ITERATIVE_THRESHOLDS = {
    "CoralReefCleanup": 5,
    "CastleCrasherPlus": 6,
    "RoverRescue": 3,
}
```

### Priority

The only priority is **wheel_spin > resilience**, and only for the single headline
status shown per student. Every trigger still fires and is logged independently
(this is data collection). There is no global ordering across all five: the headline
prefers wheel_spin over resilience when both are active; for any other combination
the API shows the most recently opened active trigger.

## Core Algorithm: `detect_run_triggers`

A single pure pass over the run `edit_distance` sequence emits every momentary fire
event as `(trigger_type, run_index, detail)`. It is deterministic over the full
sequence, so re-running it on rehydrate produces the same fire indices; the worker
dedupes against the already-fired set per type, so no alert ever double-fires.

```
state: zero_streak=0, wheel_armed=True, iter_count=0, iter_armed=True
for i, ed in enumerate(run_edit_distances):
    if ed > 0 and zero_streak >= RESILIENCE_ZERO_RUNS:
        emit("resilience", i)

    if ed == 0:
        zero_streak += 1
        if zero_streak >= WHEEL_SPIN_ZERO_RUNS and wheel_armed:
            emit("wheel_spin", i); wheel_armed = False     # cooldown until ed>0
    else:
        zero_streak = 0; wheel_armed = True                 # ed>0 re-arms

    if ed >= EXPLORER_EDIT_DISTANCE:
        emit("explorer", i)

    if ed > ITERATIVE_EDIT_MIN:                             # ed > 1
        iter_count += 1
        if iter_count >= iterative_threshold and iter_armed:
            emit("iterative", i); iter_armed = False        # cooldown until ed==0
    if ed == 0:
        iter_count = 0; iter_armed = True                   # burst boundary
```

`inactive` is **not** here -- it is time-based and handled by the sweep.

## Architecture

Four of five triggers become **worker-fired** (per-run, from the edit_distance
sequence): wheel_spin, resilience, explorer, iterative. Only **inactive** stays in
the `triggers.evaluate()` sweep (sustained, time-based).

- `app/pipeline/triggers.py`: keeps a slimmed `evaluate()` (inactive only) and gains
  `detect_run_triggers(run_edit_distances, iterative_threshold)` plus a worker-side
  helper that turns emitted events into `db.create_trigger` calls, deduped by a
  per-type fired-index set.
- `StudentWorker` holds the per-type fired-index sets (generalizing today's
  `fired_big_change`), seeded from the DB on rehydrate so a restart never re-fires.
  `db.big_change_indices` generalizes to `db.fired_indices(student_id, trigger_type)`.
- The worker's `recompute_and_write` calls `detect_run_triggers` each recompute and
  creates any new (not-yet-fired) triggers, exactly where `big_change` fires today.

## Data Model Changes

`student_state` is a derived cache (re-materialized every tick, wiped on reset):

- **Drop columns:** `current_state`, `state_label`, `stuck`, `consecutive_stuck`
  (table rebuild in `init_db`'s existing idempotent migration block).
- **`runs` JSON** becomes `[{index, edit_distance, ts}]` (drop `change_score`,
  `obs_bucket`, `hmm_state`, `obs_labels`).
- Headline **status** is derived from open `trigger_event` rows (highest-priority
  active trigger; wheel_spin outranks resilience), computed in the API response.
  No new stored status column.

API `/api/student_states/` drops `stuck`/`stuck_count`/`stuck_state`/`state_labels`;
the dashboard derives status and sort order from the triggers it already fetches.

## HMM Teardown & Cleanup

- Delete `app/strategy_hmm/model.pkl`, the HMM decode (`compute_strategy_states`
  HMM/bucket/state parts), `bucket_change_score`, and the HMM constants
  (`MODEL_PATH`, `REWRITE_THRESHOLD`, `SIMILARITY_SMOOTHING`, `OBS_LABELS`,
  `STUCK_STATE`, `STATE_LABELS`, `SUSTAINED_TRIGGERS`, `BIG_CHANGE_SCORE`).
- Keep `ast_builder.py` and APTED; APTED now returns `edit_distance`.
- **Rename** `app/strategy_hmm/` → `app/runs/`; the run-sequence builder
  (`compute_strategy_states`) becomes `compute_run_edit_distances` in
  `app/runs/run_sequence.py`, returning `[{index, edit_distance, ts}]`.
- `requirements.txt`: remove `hmmlearn`, `numpy`, `scikit-learn`, `joblib`. Keep
  `apted`.

## Frontend (full rewamp)

- Remove the strategy/HMM state track from the student detail.
- Status badge + roster sort driven by active triggers (wheel_spin headline first).
- Legend lists all five triggers.
- Per-trigger disable toggles for all five (extends the existing disabled-triggers
  meta flag).
- `frontend/src/constants.js`: 5-trigger labels/colors.

## Tests

- Delete `test_strategy_hmm.py`.
- `test_apted.py`: update for the new cost model; add an assertion that adding one
  block scores `edit_distance == 1` (edge cost 0), and that a field-only change
  scores 1.0.
- New `test_run_triggers.py`: feed integer `edit_distance` sequences to
  `detect_run_triggers` and assert the emitted `(type, index)` events -- the glass-box
  core. Cover: 6-zero streak fires wheel_spin once; cooldown until ed>0; resilience
  at a breakout after >=4 zeros; explorer at ed>=13; iterative count to 6 then
  cooldown until ed==0; both fire independently on a 6-zeros-then-edit sequence.
- `test_workers.py`: replace `consecutive_stuck`/HMM-state tests with per-type
  fire + dedupe-across-rehydrate tests built on `detect_run_triggers`.
- `test_triggers_eval.py`: inactive at 240; wheel_spin no longer in the sweep.

## Open / Future

- Per-playground Iterative thresholds: wire once the activity name is available in
  telemetry; the reference dict is already in `constants.py`.
- The cost-model change shifts historical `edit_distance` values vs any prior
  Hyeongjo run that used different costs; the config above is the agreed source of
  truth.

## Appendix: Decisions & Assumptions Ledger

Every decision behind this spec, tagged by origin so future readers can tell what
was directed vs. defaulted. **[user]** = explicitly confirmed by Maharsh;
**[deck]** = taken from the source slides; **[default]** = chosen by Claude without
explicit confirmation (open to override); **[assume]** = an unverified assumption
the implementation must check.

### Signal & cost model

- **[user]** Use the raw `edit_distance`, not the normalized `change_score`, as the
  trigger signal. (Approved the switch after it was proposed.)
- **[user]** APTED cost config is Hyeongjo's: block del/ins 1.0, edge del/ins 0,
  field/type/edge change 1.0. (Provided verbatim.)
- **[default]** `change_score`, `SIMILARITY_SMOOTHING`, and `_count_tree_nodes` are
  removed entirely rather than kept alongside `edit_distance`.
- **[default]** `BlocklyConfig.delete/insert` become edge-aware (return 0 for
  `__edge__` nodes) so the provided edge costs take effect.
- **[assume]** The deck's distributions were produced with this exact cost config;
  if not, the `>1` / `>=13` thresholds shift.
- **[assume]** Under the new costs `edit_distance` is integer-valued (all costs are
  0 or 1.0).

### Trigger definitions

- **[deck]** Five triggers replace the HMM; `big_change` folds into Explorer.
- **[deck/user]** wheel_spin: `ed == 0` streak `>= 6`; momentary; cooldown until
  `ed > 0`. (Strict `== 0` and `>= 6` both confirmed by user.)
- **[deck]** resilience: `ed > 0` after `>= 4` trailing zeros; threshold 4.
- **[user]** inactive keeps the existing any-event idle implementation, retuned to
  240s; the segmenter's `PAUSE_THRESHOLD_S = 300` is untouched.
- **[deck]** explorer: single run `ed >= 13`.
- **[user]** explorer fires once per qualifying run, deduped by index, no cooldown.
- **[deck]** iterative: count `ed > 1` runs to a threshold; cooldown until `ed == 0`.
- **[user]** iterative uses the default threshold 6 for everyone; per-playground
  dict is reference-only (activity name absent from telemetry).
- **[user]** iterative counts across the whole session (no reset on
  loadProject/newProject).
- **[default]** iterative interpretation of the deck's cooldown: an `ed == 0` run
  both clears the cooldown and resets the count to 0 (burst boundary); `ed == 1`
  neither counts nor resets.

### Priority & status

- **[user]** Only priority rule is wheel_spin > resilience, for the headline status
  only; all triggers fire/log independently. No global ordering.
- **[user]** Per-student status becomes trigger-driven (HMM strategy state dropped).
- **[default]** Headline tiebreak for any other active-trigger combination = the
  most recently opened trigger.

### Architecture

- **[default]** `detect_run_triggers` is a single pure pass over the `edit_distance`
  sequence; the four change-based triggers fire from the worker, `inactive` stays in
  the sweep.
- **[default]** Momentary triggers are idempotent via per-type fired-index sets
  seeded from the DB on rehydrate (generalizing today's `big_change` dedupe), so a
  restart or recompute never re-fires.
- **[default]** A single run may emit multiple trigger types at once (e.g. explorer
  + iterative); they are independent.
- **[default]** `RE_ALERT_SECONDS` is retained only for the sustained `inactive`
  trigger (acked-but-still-idle rotation); wheel_spin's cooldown replaces its old
  timer-based re-alert.

### Cleanup

- **[default]** Rename `app/strategy_hmm/` → `app/runs/` and
  `compute_strategy_states` → `compute_run_edit_distances`.
- **[default]** Drop `current_state`/`state_label`/`stuck`/`consecutive_stuck` from
  `student_state` via the existing idempotent migration block.
- **[user]** Frontend is fully rewamped in this task (not deferred).
- **[assume]** `hmmlearn`/`numpy`/`scikit-learn`/`joblib` are used only by the HMM
  and can be removed; verify no other importer.
- **[assume]** Nothing in the API/frontend consumes `change_score` or the strategy
  fields beyond what this spec updates.
- **[default]** This spec lives under `docs/` (mkdocs source); it must be kept out
  of the site nav or relocated if it shouldn't publish.

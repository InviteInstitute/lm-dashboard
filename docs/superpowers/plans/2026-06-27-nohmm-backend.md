# NoHMM Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the HMM strategy model with five deterministic triggers computed from each run's integer APTED `edit_distance`, and tear out the HMM entirely.

**Architecture:** Per-run `edit_distance` (raw APTED tree-edit distance, made integer by an edge-aware cost model) is the only signal. A single pure pass `detect_run_triggers` emits four momentary triggers (wheel_spin, resilience, explorer, iterative) from the worker; the sustained `inactive` trigger stays in the sweep. Per-student per-type fired-index sets (seeded from the DB) keep momentary triggers idempotent across recompute/restart.

**Tech Stack:** FastAPI, raw `sqlite3`, the `apted` library, pytest. No numpy/hmmlearn/sklearn/joblib after this plan.

**Source spec:** `docs/superpowers/specs/NoHMM.md` (read it before starting).

## Global Constraints

- Run all tests with `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest -q`. The shell working dir resets between commands, so prefix every command with `cd /Users/maharsh/Documents/Research/lm-dashboard &&`.
- `edit_distance` is a whole number under the new cost config (block del/ins 1.0, edge del/ins 0, field/type/edge change 1.0).
- Never add Co-Authored-By / "Generated with Claude" to commits.
- Work on branch `summer` (already checked out).
- Thresholds verbatim: `WHEEL_SPIN_ZERO_RUNS = 6`, `RESILIENCE_ZERO_RUNS = 4`, `INACTIVE_TRIGGER_SECONDS = 240`, `EXPLORER_EDIT_DISTANCE = 13`, `ITERATIVE_EDIT_MIN = 1`, `ITERATIVE_DEFAULT_THRESHOLD = 6`.
- Trigger types: `wheel_spin`, `resilience`, `inactive`, `explorer`, `iterative`. `big_change` is removed (folded into `explorer`).

---

## File Structure

- `app/constants.py` — MODIFY: add trigger + edge-aware cost constants; remove HMM constants (final task).
- `app/strategy_hmm/` → `app/runs/` — RENAME (final task). Within it:
  - `apted_similarity.py` — MODIFY: edge-aware `BlocklyConfig`, expose integer `edit_distance`, drop normalization.
  - `ast_builder.py` — unchanged (moves with the rename).
  - `pipeline.py` → `run_sequence.py` — REPLACE: `compute_run_edit_distances(events)`.
  - `model.pkl` — DELETE.
- `app/pipeline/triggers.py` — MODIFY: add `detect_run_triggers`; slim `evaluate()` to `inactive` only.
- `app/pipeline/workers.py` — MODIFY: build run sequence, fire momentary triggers via fired-index dedupe, drop HMM/big_change/consecutive_stuck.
- `app/db.py` — MODIFY: schema migration (drop strategy columns), `upsert_student_state`/`_student_state_row`/`all_student_states`, generalize `big_change_indices` → `fired_indices`.
- `app/main.py` — MODIFY: `_shape_state` + `student_states` response drop strategy fields; status from triggers.
- `requirements.txt` — MODIFY: remove `hmmlearn`, `numpy`, `scikit-learn`, `joblib`.
- Tests: NEW `tests/test_run_triggers.py`; UPDATE `test_apted.py`, `test_workers.py`, `test_triggers_eval.py`; DELETE `test_strategy_hmm.py`.

---

### Task 1: Add the new constants (additive, keeps suite green)

**Files:**
- Modify: `app/constants.py`

**Interfaces:**
- Produces: `WHEEL_SPIN_ZERO_RUNS`, `RESILIENCE_ZERO_RUNS`, `INACTIVE_TRIGGER_SECONDS`, `EXPLORER_EDIT_DISTANCE`, `ITERATIVE_EDIT_MIN`, `ITERATIVE_DEFAULT_THRESHOLD`, `ITERATIVE_THRESHOLDS`, `TRIGGER_PRIORITY`, and edge-aware cost constants `BLOCK_DELETE_COST`, `BLOCK_INSERT_COST`, `EDGE_DELETE_COST`, `EDGE_INSERT_COST` (plus existing `FIELD_CHANGE_COST`/`TYPE_CHANGE_COST`/`EDGE_CHANGE_COST` which change value). Adds `resilience`/`explorer`/`iterative` entries to `TRIGGER_LABELS`.

- [ ] **Step 1: Add trigger constants.** In `app/constants.py`, in the `# Triggers` section (after `RE_ALERT_SECONDS`), add:

```python
# --- Edit-distance trigger thresholds (see docs/superpowers/specs/NoHMM.md) ---
WHEEL_SPIN_ZERO_RUNS = 6        # >= this many consecutive zero-edit runs -> wheel_spin
RESILIENCE_ZERO_RUNS = 4        # an edit after >= this many zeros -> resilience
INACTIVE_TRIGGER_SECONDS = 240  # idle > this many seconds -> inactive (separate from the segmenter's 300s)
EXPLORER_EDIT_DISTANCE = 13     # a single run with edit_distance >= this -> explorer
ITERATIVE_EDIT_MIN = 1          # runs with edit_distance > this count toward iterative
ITERATIVE_DEFAULT_THRESHOLD = 6 # count of such runs that fires iterative

# Reference only -- not used until the playground name is in telemetry.
ITERATIVE_THRESHOLDS = {"CoralReefCleanup": 5, "CastleCrasherPlus": 6, "RoverRescue": 3}

# Headline-status precedence; only wheel_spin > resilience is load-bearing.
TRIGGER_PRIORITY = ("wheel_spin", "inactive", "resilience", "explorer", "iterative")
```

- [ ] **Step 2: Extend the labels.** Replace the `TRIGGER_LABELS` line with the five-trigger version (keep `big_change` for now so existing code keeps importing it; it is removed in Task 8):

```python
TRIGGER_LABELS = {
    "wheel_spin": "Wheel-spinning", "resilience": "Resilience", "inactive": "Inactive",
    "explorer": "Explorer", "iterative": "Step-by-Step", "big_change": "Big rewrite",
}
```

- [ ] **Step 3: Add edge-aware cost constants.** In the `# Strategy HMM tuning` section, next to the existing APTED costs, add (the existing `FIELD_CHANGE_COST` becomes `1.0`):

```python
BLOCK_DELETE_COST = 1.0
BLOCK_INSERT_COST = 1.0
EDGE_DELETE_COST = 0.0
EDGE_INSERT_COST = 0.0
```

Change the existing `FIELD_CHANGE_COST = 0.3` to `FIELD_CHANGE_COST = 1.0`. Leave `TYPE_CHANGE_COST`/`EDGE_CHANGE_COST` at `1.0` and `DELETION_COST`/`INSERTION_COST` in place for now (removed in Task 8).

- [ ] **Step 4: Run the suite to confirm still green.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest -q 2>&1 | tail -5`
Expected: `test_apted.py` may now show changed-cost failures (it asserts old `change_score` values) — that is handled in Task 2. If only `test_apted`/`test_strategy_hmm` fail, proceed; otherwise fix the import you broke. (If you prefer a fully-green commit, do Task 2 before committing.)

- [ ] **Step 5: Commit.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add app/constants.py && git commit -m "Add edit-distance trigger constants and edge-aware APTED costs"
```

---

### Task 2: Edge-aware cost model + integer `edit_distance` (and drop the HMM signal)

This is the coupled signal-layer swap: reworking the cost model changes `change_score`, which the HMM depends on, so the HMM decode and its tests come out here. The package keeps its `strategy_hmm` name until Task 8 (rename last, to keep this diff focused).

**Files:**
- Modify: `app/strategy_hmm/apted_similarity.py`
- Create: `app/strategy_hmm/run_sequence.py`
- Delete: `app/strategy_hmm/pipeline.py`, `app/strategy_hmm/model.pkl`, `tests/test_strategy_hmm.py`
- Modify: `tests/test_apted.py`
- Modify: `app/pipeline/workers.py` (only the import line, to keep the suite importable — full rewrite is Task 5)

**Interfaces:**
- Produces: `cached_edit_distance(prev_xml, curr_xml, prev_ast, curr_ast) -> int`, `compute_edit_distance(ast_prev, ast_curr) -> int`, `clear_cache()`. And `compute_run_edit_distances(events) -> {"runs": [{"index": int, "edit_distance": int|None, "ts": float|None}]}` in `run_sequence.py`.
- Consumes: edge-aware cost constants from Task 1.

- [ ] **Step 1: Rewrite `BlocklyConfig` to be edge-aware and return raw distance.** In `app/strategy_hmm/apted_similarity.py`, replace the cost import and the `compute_change_score`/cache section. New import block:

```python
from app.constants import (
    BLOCK_DELETE_COST, BLOCK_INSERT_COST, EDGE_DELETE_COST, EDGE_INSERT_COST,
    FIELD_CHANGE_COST, TYPE_CHANGE_COST, EDGE_CHANGE_COST,
)
```

Replace the `BlocklyConfig` class body's `delete`/`insert` and `__init__` so edges are free to add/remove:

```python
class BlocklyConfig(Config):
    """APTED cost model matching Hyeongjo's colab. Edge nodes (the synthetic
    connectors our AST inserts between parent and child) cost 0 to add/remove, so
    adding one real block scores 1, not 2."""

    def delete(self, node):
        return EDGE_DELETE_COST if node.node_type == "__edge__" else BLOCK_DELETE_COST

    def insert(self, node):
        return EDGE_INSERT_COST if node.node_type == "__edge__" else BLOCK_INSERT_COST

    def rename(self, n1, n2):
        if n1.name == n2.name:
            return 0.0
        if n1.node_type == "__edge__" or n2.node_type == "__edge__":
            return EDGE_CHANGE_COST
        if n1.node_type == n2.node_type:
            return FIELD_CHANGE_COST
        return TYPE_CHANGE_COST
```

- [ ] **Step 2: Replace the score functions with integer distance.** Replace `compute_change_score` with:

```python
def compute_edit_distance(ast_prev, ast_curr):
    """The raw APTED tree-edit distance between two run ASTs (a whole number under
    the edge-aware cost model). 0 means identical."""
    t1 = ast_to_apted_tree(ast_prev)
    t2 = ast_to_apted_tree(ast_curr)
    return int(round(APTED(t1, t2, BlocklyConfig()).compute_edit_distance()))
```

Rename the cache: `_score_cache` → `_distance_cache`, `cached_change_score` → `cached_edit_distance` (identical-XML short-circuit returns `0`, the cache stores ints), and delete `_count_tree_nodes` and the `SIMILARITY_SMOOTHING` import (now unused). Keep `clear_cache()` pointing at `_distance_cache`.

- [ ] **Step 3: Create `app/strategy_hmm/run_sequence.py`.**

```python
"""Build a chronological per-run edit-distance sequence from a student's events.
Only runProject events take part; each run after the first gets the integer APTED
edit_distance against the previous run. The first run has no predecessor (None)."""
import json

from .ast_builder import xml_to_block_ast, extract_workspace_xml
from .apted_similarity import cached_edit_distance


def _extract_runs(events):
    runs = []
    for ev in events:
        if ev.get("event_type") != "runProject":
            continue
        content = ev.get("content") or {}
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = {}
        xml = extract_workspace_xml(content)
        runs.append((xml, xml_to_block_ast(xml), ev.get("ts")))
    return runs


def compute_run_edit_distances(events):
    """Returns {"runs": [{"index": i, "edit_distance": int|None, "ts": float|None}]}."""
    runs = _extract_runs(events)
    out = []
    for i, (xml, ast, ts) in enumerate(runs):
        if i == 0:
            dist = None
        else:
            prev_xml, prev_ast, _ = runs[i - 1]
            dist = cached_edit_distance(prev_xml, xml, prev_ast, ast)
        out.append({"index": i, "edit_distance": dist, "ts": ts})
    return {"runs": out}
```

- [ ] **Step 4: Delete the HMM files.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git rm app/strategy_hmm/pipeline.py app/strategy_hmm/model.pkl tests/test_strategy_hmm.py
```

- [ ] **Step 5: Keep the suite importable.** In `app/pipeline/workers.py`, change the import line `from app.strategy_hmm.pipeline import compute_strategy_states` to `from app.strategy_hmm.run_sequence import compute_run_edit_distances`. (The body still references `compute_strategy_states`; that is fully rewritten in Task 5. To avoid a red import now, also add at the top of `recompute_and_write` a temporary `compute_strategy_states = lambda e: {"runs": [], "obs_labels": {}}` — OR sequence Task 5 immediately after and commit them together. Prefer committing Tasks 2+5 together.)

- [ ] **Step 6: Rewrite `tests/test_apted.py` for the new costs.** Replace the change-score tests with edit-distance ones. Key assertions:

```python
from app.strategy_hmm import apted_similarity as A
from app.strategy_hmm.ast_builder import xml_to_block_ast


def test_identical_workspaces_distance_zero():
    xml = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    ast = xml_to_block_ast(xml)
    assert A.compute_edit_distance(ast, ast) == 0


def test_adding_one_block_costs_one():
    # one hat block -> hat block with a child; edge node is free, so distance == 1
    a = xml_to_block_ast('<xml><block type="events_whenStarted" id="a"></block></xml>')
    b = xml_to_block_ast('<xml><block type="events_whenStarted" id="a">'
                         '<next><block type="motor_on" id="b"></block></next></block></xml>')
    assert A.compute_edit_distance(a, b) == 1


def test_field_only_change_costs_one():
    a = xml_to_block_ast('<xml><block type="motor_on" id="b"><field name="PORT">A</field></block></xml>')
    b = xml_to_block_ast('<xml><block type="motor_on" id="b"><field name="PORT">B</field></block></xml>')
    assert A.compute_edit_distance(a, b) == 1


def test_cache_short_circuits_identical_xml():
    A.clear_cache()
    assert A.cached_edit_distance("<xml/>", "<xml/>", None, None) == 0
```

Keep the existing `test_make_node_label_variants` / `test_ast_to_tree_*` / `test_edge_nodes_toggle_*` tests (label/tree logic is unchanged).

- [ ] **Step 7: Run apted tests.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest tests/test_apted.py -q 2>&1 | tail -8`
Expected: PASS. (If `test_adding_one_block_costs_one` is not 1, print the value and confirm the AST inserts an `__edge__` node for `next` and that `delete/insert` return 0 for it.)

- [ ] **Step 8: Commit (together with Task 5 for a green suite).**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add -A app/strategy_hmm tests/test_apted.py app/pipeline/workers.py && git commit -m "Replace HMM signal with integer edit_distance run sequence"
```

---

### Task 3: `detect_run_triggers` — the glass-box scanner

**Files:**
- Modify: `app/pipeline/triggers.py`
- Create: `tests/test_run_triggers.py`

**Interfaces:**
- Consumes: trigger constants from Task 1.
- Produces: `detect_run_triggers(edit_distances, iterative_threshold=ITERATIVE_DEFAULT_THRESHOLD) -> list[tuple[str, int, dict]]` where each item is `(trigger_type, run_index, detail)`. `edit_distances` is the per-run list (the first element is `None`).

- [ ] **Step 1: Write the failing test file `tests/test_run_triggers.py`.**

```python
"""The single-pass run-trigger scanner: wheel_spin / resilience / explorer / iterative
from an integer edit_distance sequence. The first element is None (first run)."""
from app.pipeline.triggers import detect_run_triggers


def _types(seq, **kw):
    return [(t, i) for (t, i, _d) in detect_run_triggers(seq, **kw)]


def test_six_zero_streak_fires_wheel_spin_once():
    # None, then six zeros: wheel_spin fires at index 6 (the 6th zero), only once
    seq = [None, 0, 0, 0, 0, 0, 0]
    assert ("wheel_spin", 6) in _types(seq)
    assert sum(1 for t, _ in _types(seq) if t == "wheel_spin") == 1


def test_wheel_spin_rearms_after_edit():
    seq = [None, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0]
    fires = [i for t, i in _types(seq) if t == "wheel_spin"]
    assert fires == [6, 13]


def test_resilience_fires_on_breakout_after_four_zeros():
    seq = [None, 0, 0, 0, 0, 2]      # four zeros then an edit
    assert ("resilience", 5) in _types(seq)


def test_no_resilience_with_only_three_zeros():
    seq = [None, 0, 0, 0, 2]
    assert all(t != "resilience" for t, _ in _types(seq))


def test_explorer_fires_each_big_change():
    seq = [None, 13, 5, 20]
    assert [i for t, i in _types(seq) if t == "explorer"] == [1, 3]


def test_iterative_fires_at_threshold_then_cooldown_until_zero():
    # six runs of edit_distance > 1 -> fires at the 6th; then needs a 0 to re-arm
    seq = [None, 2, 2, 2, 2, 2, 2, 2, 0, 3, 3, 3, 3, 3, 3]
    fires = [i for t, i in _types(seq) if t == "iterative"]
    assert fires == [6, 14]


def test_iterative_ignores_distance_one():
    seq = [None, 1, 1, 1, 1, 1, 1, 1]
    assert all(t != "iterative" for t, _ in _types(seq))


def test_wheel_spin_and_resilience_both_fire_on_long_then_edit():
    seq = [None, 0, 0, 0, 0, 0, 0, 0, 1]   # 7 zeros then an edit
    kinds = _types(seq)
    assert ("wheel_spin", 6) in kinds and ("resilience", 8) in kinds
```

- [ ] **Step 2: Run it to confirm it fails.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest tests/test_run_triggers.py -q 2>&1 | tail -5`
Expected: FAIL with `ImportError: cannot import name 'detect_run_triggers'`.

- [ ] **Step 3: Implement `detect_run_triggers` in `app/pipeline/triggers.py`.** Add the constants to the import from `app.constants` and add the function:

```python
from app.constants import (
    WHEEL_SPIN_ZERO_RUNS, RESILIENCE_ZERO_RUNS, EXPLORER_EDIT_DISTANCE,
    ITERATIVE_EDIT_MIN, ITERATIVE_DEFAULT_THRESHOLD, TRIGGER_LABELS as LABELS,
)


def detect_run_triggers(edit_distances, iterative_threshold=ITERATIVE_DEFAULT_THRESHOLD):
    """One pure pass over a per-run edit_distance sequence (first element None).
    Emits (trigger_type, run_index, detail) for each momentary fire. Deterministic,
    so the worker can re-run it and dedupe by run_index without double-firing."""
    out = []
    zero_streak = 0
    wheel_armed = True
    iter_count = 0
    iter_armed = True
    for i, ed in enumerate(edit_distances):
        if ed is None:
            continue
        if ed > 0 and zero_streak >= RESILIENCE_ZERO_RUNS:
            out.append(("resilience", i, {"label": LABELS["resilience"],
                                          "value": f"recovered after {zero_streak} reruns"}))
        if ed == 0:
            zero_streak += 1
            if zero_streak >= WHEEL_SPIN_ZERO_RUNS and wheel_armed:
                out.append(("wheel_spin", i, {"label": LABELS["wheel_spin"],
                                              "value": f"{zero_streak} identical reruns"}))
                wheel_armed = False
        else:
            zero_streak = 0
            wheel_armed = True
        if ed >= EXPLORER_EDIT_DISTANCE:
            out.append(("explorer", i, {"label": LABELS["explorer"], "value": f"changed {ed}"}))
        if ed > ITERATIVE_EDIT_MIN:
            iter_count += 1
            if iter_count >= iterative_threshold and iter_armed:
                out.append(("iterative", i, {"label": LABELS["iterative"],
                                             "value": f"{iter_count} steady edits"}))
                iter_armed = False
        if ed == 0:
            iter_count = 0
            iter_armed = True
    return out
```

- [ ] **Step 4: Run the test to confirm it passes.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest tests/test_run_triggers.py -q 2>&1 | tail -5`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add app/pipeline/triggers.py tests/test_run_triggers.py && git commit -m "Add detect_run_triggers single-pass scanner"
```

---

### Task 4: DB — drop strategy columns, generalize the fired-index seed

**Files:**
- Modify: `app/db.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `fired_indices(student_id, trigger_type) -> set[int]` (generalizes `big_change_indices`). `student_state` rows no longer carry `current_state`/`state_label`/`stuck`/`consecutive_stuck`; `_student_state_row` and `all_student_states` no longer return them.

- [ ] **Step 1: Update the schema and add a migration.** In `app/db.py`, in `_SCHEMA`, change the `student_state` table to drop the four strategy columns (lines ~193-194):

```sql
CREATE TABLE IF NOT EXISTS student_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    studentID VARCHAR(128) NOT NULL UNIQUE,
    classCode VARCHAR(64),
    run_count INTEGER NOT NULL DEFAULT 0, event_count INTEGER NOT NULL DEFAULT 0,
    runs TEXT, episodes TEXT,
    playground_prompt TEXT, playground_time DATETIME,
    last_event_id BIGINT NOT NULL DEFAULT 0, last_event_time DATETIME,
    updated_at DATETIME NOT NULL
);
```

In `init_db()`'s migration block, add an idempotent rebuild for older DBs that still have the columns (SQLite can drop columns since 3.35, which this project's 3.53 supports):

```python
        sscols = {r[1] for r in con.execute("PRAGMA table_info(student_state)")}
        for dead in ("current_state", "state_label", "stuck", "consecutive_stuck"):
            if dead in sscols:
                con.execute(f"ALTER TABLE student_state DROP COLUMN {dead}")
```

- [ ] **Step 2: Trim `_student_state_row`.** Remove the `current_state`, `state_label`, `stuck`, `consecutive_stuck` keys from the dict returned by `_student_state_row` (lines ~438-441).

- [ ] **Step 3: Trim `all_student_states`.** Change its query and dict to only what the sweep needs now (`inactive` needs `last_event_time`; keep `runs` out — the sweep no longer reads runs):

```python
def all_student_states():
    rows = _query("SELECT studentID, last_event_time FROM student_state")
    return [{"studentID": r["studentID"],
             "last_event_time": db_to_dt(r["last_event_time"])} for r in rows]
```

- [ ] **Step 4: Generalize the fired-index seed.** Replace `big_change_indices` with:

```python
def fired_indices(student_id, trigger_type):
    """Run indices that already produced a momentary trigger of this type, so a
    cold worker seeds its in-memory dedupe and never re-fires an old run."""
    rows = _query(
        "SELECT json_extract(detail, '$.run_index') AS i FROM trigger_event "
        "WHERE studentID = ? AND trigger_type = ?",
        (student_id, trigger_type),
    )
    return {r["i"] for r in rows if r["i"] is not None}
```

- [ ] **Step 5: Write a test for the migration + fired_indices.** In `tests/test_db_internals.py` add:

```python
def test_fired_indices_filters_by_type():
    t = db.now()
    db.create_trigger("s1", "explorer", started_at=t, last_seen_at=t, resolved_at=t,
                      detail={"run_index": 3})
    db.create_trigger("s1", "wheel_spin", started_at=t, last_seen_at=t, resolved_at=t,
                      detail={"run_index": 7})
    assert db.fired_indices("s1", "explorer") == {3}
    assert db.fired_indices("s1", "wheel_spin") == {7}
```

- [ ] **Step 6: Run the db tests.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest tests/test_db_internals.py tests/test_db_triggers.py -q 2>&1 | tail -8`
Expected: PASS. (The fresh test DB is built from `_SCHEMA`, so the migration branch is a no-op there; it only matters for the live DB.)

- [ ] **Step 7: Commit.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add app/db.py tests/test_db_internals.py && git commit -m "Drop strategy columns from student_state; generalize fired_indices"
```

---

### Task 5: Worker rewrite — fire momentary triggers, drop the HMM/big_change layer

**Files:**
- Modify: `app/pipeline/workers.py`
- Modify: `tests/test_workers.py`

**Interfaces:**
- Consumes: `compute_run_edit_distances` (Task 2), `detect_run_triggers` (Task 3), `db.fired_indices` (Task 4).
- Produces: `student_state.runs` JSON `{"runs": [{index, edit_distance, ts}], "run_count": int}`. No `current_state`/`stuck`/`consecutive_stuck` in the upsert.

- [ ] **Step 1: Replace the strategy/big_change machinery in `StudentWorker`.** In `app/pipeline/workers.py`:
  - Imports: drop `STUCK_STATE, STATE_LABELS` and the `apted_similarity.clear_cache` alias stays; import `from app.strategy_hmm.run_sequence import compute_run_edit_distances` and `from app.pipeline.triggers import detect_run_triggers`.
  - `__init__`: replace `self.fired_big_change = set()` and `self._runs_cache = None` with `self.fired = {t: set() for t in ("wheel_spin", "resilience", "explorer", "iterative")}` and `self._runs_cache = None`.
  - In `recompute_and_write`, replace the strategy decode + big_change block + states/consecutive_stuck computation with:

```python
        events = list(self.events)
        if self.had_new_run or self._runs_cache is None:
            self._runs_cache = compute_run_edit_distances(events)
            self.had_new_run = False
        runs = self._runs_cache["runs"]
        run_count = len(runs)
        edit_distances = [r["edit_distance"] for r in runs]

        # Fire the four momentary triggers, deduped per type by run index.
        for ttype, idx, detail in detect_run_triggers(edit_distances):
            if ttype in disabled or idx in self.fired[ttype]:
                continue
            detail = {**detail, "run_index": idx}
            ts = runs[idx].get("ts")
            at = (datetime.fromtimestamp(ts, tz=timezone.utc) if ts else db.now())
            db.create_trigger(self.student_id, ttype, started_at=at, last_seen_at=at,
                              resolved_at=at, detail=detail)
            self.fired[ttype].add(idx)
```

  (add `from datetime import datetime, timezone` at the top.)
  - In the `db.upsert_student_state(...)` call, remove `current_state`, `state_label`, `stuck`, `consecutive_stuck`; change the `runs` value to `{"runs": runs, "run_count": run_count}`.
  - `_rehydrate`: replace `worker.fired_big_change = db.big_change_indices(...)` with:

```python
    for t in worker.fired:
        worker.fired[t] = db.fired_indices(worker.student_id, t)
```

- [ ] **Step 2: Rewrite the worker tests.** In `tests/test_workers.py`, delete the `consecutive_stuck`/`hmm_state`/`big_change` tests and the `_worker_with_runs` HMM seeding. Add tests driving the new path. Helper + cases:

```python
def _worker_with_distances(sid, dists):
    """A worker whose run sequence is pre-seeded with edit_distances (index 0 = None)."""
    w = workers.StudentWorker(sid)
    w._runs_cache = {"runs": [{"index": i, "edit_distance": d, "ts": float(i)}
                              for i, d in enumerate(dists)]}
    w.had_new_run = False
    return w


def test_wheel_spin_fires_once_and_dedupes_across_recompute():
    w = _worker_with_distances("s1", [None, 0, 0, 0, 0, 0, 0])
    w.recompute_and_write()
    w.recompute_and_write()
    rows = db._query("SELECT 1 FROM trigger_event WHERE trigger_type='wheel_spin'")
    assert len(rows) == 1


def test_explorer_fires_per_big_run():
    w = _worker_with_distances("s1", [None, 13, 2, 20])
    w.recompute_and_write()
    rows = db._query("SELECT json_extract(detail,'$.run_index') i FROM trigger_event "
                     "WHERE trigger_type='explorer'")
    assert sorted(r["i"] for r in rows) == [1, 3]


def test_disabled_trigger_does_not_fire():
    w = _worker_with_distances("s1", [None, 0, 0, 0, 0, 0, 0])
    w.recompute_and_write(disabled={"wheel_spin"})
    assert db._query("SELECT 1 FROM trigger_event WHERE trigger_type='wheel_spin'") == []


def test_fired_dedupe_seeded_from_db_on_rehydrate():
    w = _worker_with_distances("s1", [None, 13])
    w.recompute_and_write()
    w2 = workers.StudentWorker("s1")
    for t in w2.fired:
        w2.fired[t] = db.fired_indices("s1", t)
    w2._runs_cache = {"runs": [{"index": 0, "edit_distance": None, "ts": 0.0},
                               {"index": 1, "edit_distance": 13, "ts": 1.0}]}
    w2.had_new_run = False
    w2.recompute_and_write()
    rows = db._query("SELECT 1 FROM trigger_event WHERE trigger_type='explorer'")
    assert len(rows) == 1
```

Keep the route/rehydrate/double-count tests and the playground-prompt test (update `_worker_with_runs` references to `_worker_with_distances`).

- [ ] **Step 3: Run worker + run-trigger tests.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest tests/test_workers.py tests/test_run_triggers.py -q 2>&1 | tail -8`
Expected: PASS.

- [ ] **Step 4: Commit (with Task 2 if not yet committed).**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add app/pipeline/workers.py tests/test_workers.py && git commit -m "Worker fires edit-distance triggers; drop HMM state and big_change"
```

---

### Task 6: Slim the trigger sweep to `inactive` at 240s

**Files:**
- Modify: `app/pipeline/triggers.py`
- Modify: `tests/test_triggers_eval.py`

**Interfaces:**
- Consumes: `INACTIVE_TRIGGER_SECONDS`.
- Produces: `evaluate(now=None, disabled=None)` that only reconciles the sustained `inactive` trigger.

- [ ] **Step 1: Remove wheel_spin/big_change from the sweep.** In `app/pipeline/triggers.py`:
  - Change the import from `STUCK_STATE as WHEEL_SPIN_STATE, INACTIVE_SECONDS, BIG_CHANGE_SCORE, ...` to use `INACTIVE_TRIGGER_SECONDS` and drop `STUCK_STATE`/`BIG_CHANGE_SCORE`/`SUSTAINED`.
  - Delete `_wheel_spin_started` (HMM-based).
  - In `evaluate`, delete the entire `# ---- wheel_spin ----` block; keep only the `inactive` block, and change its threshold/started math from `INACTIVE_SECONDS` to `INACTIVE_TRIGGER_SECONDS`.

```python
def evaluate(now=None, disabled=None):
    """Sweep student_state for the one sustained trigger, inactive."""
    now = now or db.now()
    if disabled is None:
        disabled = _disabled_types()
    for s in db.all_student_states():
        sid = s["studentID"]
        idle = (now - s["last_event_time"]).total_seconds() if s["last_event_time"] else None
        is_inactive = (idle is not None and idle >= INACTIVE_TRIGGER_SECONDS
                       and "inactive" not in disabled)
        _sustain(sid, "inactive", active=is_inactive, now=now,
                 started=(s["last_event_time"] + timedelta(seconds=INACTIVE_TRIGGER_SECONDS)
                          if s["last_event_time"] else now),
                 detail={"label": LABELS["inactive"], "value": _fmt_idle(idle)})
```

- [ ] **Step 2: Update `tests/test_triggers_eval.py`.** Remove the `wheel_spin` sweep tests. Update the inactive test to use 240s. Example:

```python
def test_inactive_fires_only_past_240s():
    from app.constants import INACTIVE_TRIGGER_SECONDS
    assert INACTIVE_TRIGGER_SECONDS == 240
    t0 = db.now()
    db.upsert_student_state("s1", {"last_event_time": t0 - timedelta(seconds=300)})
    triggers.evaluate(now=t0)
    assert db.current_open_trigger("s1", "inactive") is not None
```

(adjust imports/helpers to the file's existing style; keep the disabled-type and sustained-dedup tests, retargeted to `inactive`.)

- [ ] **Step 3: Run the trigger eval tests.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest tests/test_triggers_eval.py tests/test_trigger_helpers.py -q 2>&1 | tail -8`
Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add app/pipeline/triggers.py tests/test_triggers_eval.py && git commit -m "Slim trigger sweep to inactive at 240s"
```

---

### Task 7: API — drop strategy fields, derive status from triggers

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `db.list_student_states`, `db.triggers_feed` (existing).
- Produces: `/api/student_states/` payload without `current_state`/`current_label`/`stuck`/`consecutive_stuck`/`state_sequence`/`hmm`/`stuck_count`/`stuck_state`/`state_labels`; `runs` exposed under `runs` key; status left to the dashboard (which already fetches triggers).

- [ ] **Step 1: Rewrite `_shape_state`.** Remove the strategy keys; expose the run sequence directly:

```python
    runs_blob = s["runs"] or {}
    out = {
        "studentID": s["studentID"],
        "classCode": s["classCode"],
        "run_count": s["run_count"],
        "event_count": s["event_count"],
        "last_seen": _iso(s["last_event_time"]),
        "runs": runs_blob,                  # {runs:[{index,edit_distance,ts}], run_count}
        "episodes": s["episodes"],
        "updated_at": _iso(s["updated_at"]),
    }
    if heavy:
        out["block"] = {"llm_prompt": s["playground_prompt"],
                        "timestamp": _iso(s["playground_time"])}
    return out
```

- [ ] **Step 2: Rewrite the `student_states` response.** Drop the `stuck` sort and the stuck/state response keys; import line drops `STUCK_STATE, STATE_LABELS`:

```python
    rows = [_shape_state(s) for s in db.list_student_states(ids, classCode)]
    rows.sort(key=lambda s: s["last_seen"] or "", reverse=True)
    return {"students": rows, "student_count": len(rows)}
```

- [ ] **Step 3: Update `tests/test_api.py`.** Replace assertions that read `stuck`/`stuck_count`/`state_labels`/`hmm` with the new shape. Example edits: `test_student_states_list_is_light` asserts `"runs" in s and "current_state" not in s`; delete `test_student_states_stuck_sorts_first` (no stuck field) or replace with a recency-sort assertion. Keep the detail/404/too-many-ids/class-code tests, adjusting any strategy-field reads.

- [ ] **Step 4: Run the API tests.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest tests/test_api.py -q 2>&1 | tail -8`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add app/main.py tests/test_api.py && git commit -m "Drop strategy fields from student_states API"
```

---

### Task 8: Final teardown — remove dead constants/deps, rename the package

**Files:**
- Modify: `app/constants.py`, `requirements.txt`
- Rename: `app/strategy_hmm/` → `app/runs/` (and all importers)

**Interfaces:**
- Consumes: nothing new.
- Produces: a clean tree with no HMM references and no numpy/hmmlearn/sklearn/joblib.

- [ ] **Step 1: Remove dead constants.** In `app/constants.py` delete `STUCK_STATE`, `STATE_LABELS`, `SUSTAINED_TRIGGERS`, `BIG_CHANGE_SCORE`, `INACTIVE_SECONDS`, the entire `# Strategy HMM tuning` block except the APTED costs still used (`BLOCK_*`, `EDGE_*`, `FIELD_CHANGE_COST`, `TYPE_CHANGE_COST`, `EDGE_CHANGE_COST`) — i.e. remove `MODEL_PATH`, `REWRITE_THRESHOLD`, `SIMILARITY_SMOOTHING`, `OBS_LABELS`, `DELETION_COST`, `INSERTION_COST`. Remove `big_change` from `TRIGGER_LABELS`.

- [ ] **Step 2: Confirm nothing still imports the removed names.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && grep -rn "STUCK_STATE\|STATE_LABELS\|BIG_CHANGE_SCORE\|big_change\|REWRITE_THRESHOLD\|OBS_LABELS\|MODEL_PATH\|SIMILARITY_SMOOTHING\|compute_strategy_states" app/ tests/`
Expected: no matches (fix any that remain).

- [ ] **Step 3: Rename the package.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git mv app/strategy_hmm app/runs
grep -rl "strategy_hmm" app/ tests/ | xargs sed -i '' 's/strategy_hmm/runs/g'
```

Verify: `grep -rn "strategy_hmm" app/ tests/` returns nothing.

- [ ] **Step 4: Remove the dead dependencies.** In `requirements.txt` delete the `hmmlearn`, `numpy`, `scikit-learn`, and `joblib` lines. Keep `apted`.

- [ ] **Step 5: Run the FULL suite.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -m pytest -q 2>&1 | tail -12`
Expected: all PASS, no import errors.

- [ ] **Step 6: Confirm the app imports without the removed deps.**

Run: `cd /Users/maharsh/Documents/Research/lm-dashboard && .venv/bin/python -c "import app.main, app.pipeline.daemon, app.pipeline.workers; print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Commit.**

```bash
cd /Users/maharsh/Documents/Research/lm-dashboard && git add -A && git commit -m "Remove HMM constants/deps; rename strategy_hmm package to runs"
```

---

## Self-Review

- **Spec coverage:** signal+cost (T1,T2) ✓; five triggers (T3 momentary, T6 inactive) ✓; detect_run_triggers (T3) ✓; worker-fired + fired-index dedupe (T4,T5) ✓; data-model drop (T4) ✓; HMM teardown + rename + deps (T8) ✓; API (T7) ✓; tests (each task) ✓. Frontend = Plan 2 (separate). Feed-linger needs no code (existing `TRIGGER_RECENT_SECONDS`), so no task — verify `triggers_feed` still applies it after T6/T7.
- **Placeholder scan:** no TBD/TODO; all code blocks concrete.
- **Type consistency:** `compute_run_edit_distances` → `{"runs":[{index,edit_distance,ts}]}` used identically in T2/T5/T7; `detect_run_triggers` returns `(type, index, detail)` used identically in T3/T5; `fired_indices(sid, type)` defined T4, used T5.

## Notes for the implementer

- Tasks 2 and 5 are coupled (the worker import). If you implement strictly one task per commit, expect the suite to be red between the T2 commit and the T5 commit; prefer implementing T2→T5 back-to-back, or use the temporary shim noted in T2 Step 5.
- After T8, the live `db.sqlite3` (gitignored) will migrate its `student_state` columns on next `init_db()`; back it up first if you care about the current cache (it re-materializes anyway).

# Playground-Aware Run Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the run-based intervention triggers playground-aware, so a student who switches VEX playgrounds is analyzed per playground, with a hard reset at each switch and the per-playground Step-by-Step threshold applied.

**Architecture:** Attribute each run to its playground and null the edit distance at each playground switch (`run_sequence.py`); slice runs into contiguous same-playground stretches and run the existing pure `detect_run_triggers` once per stretch with that playground's threshold (`triggers.py`); the worker calls the new segmentation entry point instead of the flat one (`workers.py`).

**Tech Stack:** Python 3.12+, standard library, APTED (already a dependency), pytest.

## Global Constraints

- Daemon-only change. No database schema, read API, or frontend change.
- Corrected thresholds: `ITERATIVE_THRESHOLDS = {"CastleCrasherPlus": 6, "CoralReefRescue": 5, "RoverRescue": 3}` (the old `CoralReefCleanup` key never appears in telemetry).
- Read a run's playground with `.get("playground")`, defaulting to `None`, so runs built without the field (older cached rows, test fixtures) behave as a single default-threshold stretch instead of raising.
- A missing/unparseable `playground` is a continuation of the current stretch (carry the last known name, no reset), never a switch.
- The hard reset applies to all four run-based triggers (wheel_spin, resilience, explorer, iterative), because a cross-playground edit distance is meaningless for every one of them. `inactive` is unaffected (time-based, in the sweep).
- Unlisted playgrounds fall back to `ITERATIVE_DEFAULT_THRESHOLD` (6) and still fire normally.
- No AI attribution in commit messages.

---

### Task 1: Correct the ITERATIVE_THRESHOLDS keys

**Files:**
- Modify: `app/constants.py` (the `ITERATIVE_THRESHOLDS` line, ~29)
- Test: `tests/test_constants_thresholds.py` (create)

**Interfaces:**
- Produces: `ITERATIVE_THRESHOLDS: dict[str, int]` with keys exactly `"CastleCrasherPlus"`, `"CoralReefRescue"`, `"RoverRescue"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_constants_thresholds.py`:

```python
from app.constants import ITERATIVE_THRESHOLDS


def test_thresholds_use_real_telemetry_playground_names():
    # These are the exact strings that appear in the runProject `playground` field.
    assert ITERATIVE_THRESHOLDS == {
        "CastleCrasherPlus": 6,
        "CoralReefRescue": 5,
        "RoverRescue": 3,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_constants_thresholds.py -v`
Expected: FAIL — the current dict has `CoralReefCleanup`, not `CoralReefRescue`.

- [ ] **Step 3: Fix the constant**

In `app/constants.py`, replace the `ITERATIVE_THRESHOLDS` line and its comment:

```python
# Per-playground Step-by-Step thresholds, keyed by the exact `playground` string
# in the runProject telemetry. An unlisted playground uses ITERATIVE_DEFAULT_THRESHOLD.
ITERATIVE_THRESHOLDS = {"CastleCrasherPlus": 6, "CoralReefRescue": 5, "RoverRescue": 3}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_constants_thresholds.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/constants.py tests/test_constants_thresholds.py
git commit -m "Correct ITERATIVE_THRESHOLDS keys to match telemetry playground names"
```

---

### Task 2: Attribute runs to playgrounds and reset the baseline at switches

**Files:**
- Modify: `app/runs/run_sequence.py` (`_extract_runs`, `compute_run_edit_distances`)
- Test: `tests/test_run_sequence_playground.py` (create)

**Interfaces:**
- Consumes: `events` list of `{"event_type", "content", "ts"}` where a runProject event's `content` (dict or JSON string) has a top-level `"playground"` and a `"project"` holding the workspace.
- Produces: `compute_run_edit_distances(events) -> {"runs": [{"index": int, "edit_distance": int|None, "ts": float|None, "playground": str|None}, ...]}`. `edit_distance` is `None` for the first run overall and for the first run of each new contiguous playground stretch.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_sequence_playground.py`:

```python
from app.runs.run_sequence import compute_run_edit_distances

XA = '<xml><block type="events_whenStarted" id="a"></block></xml>'
XB = ('<xml><block type="events_whenStarted" id="a">'
      '<next><block type="motor_on" id="b"></block></next></block></xml>')


def _run(xml, playground, ts):
    content = {"project": {"workspace": xml}}
    if playground is not None:
        content["playground"] = playground
    return {"event_type": "runProject", "ts": ts, "content": content}


def test_runs_are_tagged_with_playground():
    runs = compute_run_edit_distances(
        [_run(XA, "RoverRescue", 0.0), _run(XB, "RoverRescue", 1.0)]
    )["runs"]
    assert [r["playground"] for r in runs] == ["RoverRescue", "RoverRescue"]


def test_first_run_of_a_new_playground_resets_edit_distance_to_none():
    # Two RoverRescue runs then a switch to CastleCrasherPlus. The switch run's
    # workspace differs from the previous run, but the distance must be None
    # because it has no predecessor *in its own playground*.
    runs = compute_run_edit_distances([
        _run(XA, "RoverRescue", 0.0),
        _run(XB, "RoverRescue", 1.0),
        _run(XA, "CastleCrasherPlus", 2.0),
    ])["runs"]
    assert runs[0]["edit_distance"] is None          # first run overall
    assert runs[1]["edit_distance"] is not None       # within the RoverRescue stretch
    assert runs[2]["edit_distance"] is None           # first run of the new stretch
    assert runs[2]["playground"] == "CastleCrasherPlus"


def test_missing_playground_continues_the_current_stretch():
    # Second run has no playground field -> it carries the previous name and is
    # NOT treated as a switch, so its distance is computed normally.
    runs = compute_run_edit_distances([
        _run(XA, "RoverRescue", 0.0),
        _run(XB, None, 1.0),
    ])["runs"]
    assert runs[1]["playground"] == "RoverRescue"
    assert runs[1]["edit_distance"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_run_sequence_playground.py -v`
Expected: FAIL — runs have no `"playground"` key (KeyError / assertion), and the switch distance is currently computed rather than `None`.

- [ ] **Step 3: Implement the playground attribution and baseline reset**

In `app/runs/run_sequence.py`, replace `_extract_runs` and `compute_run_edit_distances`:

```python
def _extract_runs(events):
    """For each runProject event, in order, pull out the workspace XML, parse it
    into a block AST, read the playground name, and pair them with the timestamp."""
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
        playground = content.get("playground")
        runs.append((xml, xml_to_block_ast(xml), ev.get("ts"), playground))
    return runs


def compute_run_edit_distances(events):
    """Return {"runs": [{"index", "edit_distance", "ts", "playground"}]}. The
    edit_distance is None for the first run overall and for the first run of each
    contiguous same-playground stretch (no cross-playground diff). A missing
    playground continues the current stretch rather than starting a new one."""
    runs = _extract_runs(events)
    out = []
    prev_pg = None
    for i, (xml, ast, ts, playground) in enumerate(runs):
        pg = playground if playground is not None else prev_pg
        if i == 0 or pg != prev_pg:
            dist = None
        else:
            prev_xml, prev_ast, _, _ = runs[i - 1]
            dist = cached_edit_distance(prev_xml, xml, prev_ast, ast)
        out.append({"index": i, "edit_distance": dist, "ts": ts, "playground": pg})
        prev_pg = pg
    return {"runs": out}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_run_sequence_playground.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/runs/run_sequence.py tests/test_run_sequence_playground.py
git commit -m "Attribute runs to playgrounds and null the edit distance at each switch"
```

---

### Task 3: Segment runs by playground and detect triggers per stretch

**Files:**
- Modify: `app/pipeline/triggers.py` (add `detect_run_triggers_by_playground`, import the thresholds)
- Test: `tests/test_triggers_by_playground.py` (create)

**Interfaces:**
- Consumes: `runs` list from Task 2 (`{"index", "edit_distance", "ts", "playground"}`); the existing pure `detect_run_triggers(edit_distances, iterative_threshold=...) -> [(type, local_index, detail)]`; `ITERATIVE_THRESHOLDS`, `ITERATIVE_DEFAULT_THRESHOLD`.
- Produces: `detect_run_triggers_by_playground(runs) -> [(trigger_type: str, run_index: int, detail: dict), ...]` with global run indices.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_triggers_by_playground.py`:

```python
from app.pipeline.triggers import detect_run_triggers_by_playground


def _runs(*specs):
    # specs: (edit_distance, playground) tuples, in order.
    return [{"index": i, "edit_distance": d, "ts": None, "playground": pg}
            for i, (d, pg) in enumerate(specs)]


def _types_and_indices(out):
    return [(t, i) for t, i, _ in out]


def test_rover_rescue_fires_step_by_step_at_three():
    # RoverRescue threshold is 3; three runs with edit_distance > 1 after the
    # stretch's null baseline reach it.
    out = detect_run_triggers_by_playground(_runs(
        (None, "RoverRescue"), (2, "RoverRescue"), (2, "RoverRescue"), (2, "RoverRescue"),
    ))
    assert ("iterative", 3) in _types_and_indices(out)


def test_castle_crasher_does_not_fire_step_by_step_at_three():
    # Same shape, but CastleCrasherPlus needs 6, so three is not enough.
    out = detect_run_triggers_by_playground(_runs(
        (None, "CastleCrasherPlus"), (2, "CastleCrasherPlus"),
        (2, "CastleCrasherPlus"), (2, "CastleCrasherPlus"),
    ))
    assert not any(t == "iterative" for t, _, _ in out)


def test_jump_back_to_a_playground_does_not_resume_the_old_count():
    # Two separate RoverRescue visits of two edits each. If they combined, the
    # count would reach 4 (>= 3) and fire; kept separate, neither reaches 3.
    out = detect_run_triggers_by_playground(_runs(
        (None, "RoverRescue"), (2, "RoverRescue"),          # visit 1: count 1
        (None, "CastleCrasherPlus"), (2, "CastleCrasherPlus"),
        (None, "RoverRescue"), (2, "RoverRescue"),          # visit 2: fresh count 1
    ))
    assert not any(t == "iterative" for t, _, _ in out)


def test_unlisted_playground_uses_default_threshold_and_still_fires():
    # ArtCanvas is not in the dict -> default 6.
    specs = [(None, "ArtCanvas")] + [(2, "ArtCanvas")] * 6
    out = detect_run_triggers_by_playground(_runs(*specs))
    assert ("iterative", 6) in _types_and_indices(out)


def test_indices_are_global_across_stretches():
    # A big edit inside the SECOND stretch fires explorer at its global index.
    out = detect_run_triggers_by_playground(_runs(
        (None, "RoverRescue"), (2, "RoverRescue"),
        (None, "CastleCrasherPlus"), (13, "CastleCrasherPlus"),
    ))
    assert ("explorer", 3) in _types_and_indices(out)


def test_missing_playground_key_defaults_to_a_single_stretch():
    # Runs built without a "playground" key must not raise.
    runs = [{"index": 0, "edit_distance": None, "ts": None},
            {"index": 1, "edit_distance": 2, "ts": None}]
    assert detect_run_triggers_by_playground(runs) == \
        [] or isinstance(detect_run_triggers_by_playground(runs), list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_triggers_by_playground.py -v`
Expected: FAIL with `ImportError` / `AttributeError` — `detect_run_triggers_by_playground` does not exist yet.

- [ ] **Step 3: Implement the segmentation function**

In `app/pipeline/triggers.py`, add `ITERATIVE_THRESHOLDS` to the existing constants import, then add the function below `detect_run_triggers`:

Update the import block:

```python
from app.constants import (
    INACTIVE_TRIGGER_SECONDS, RE_ALERT_SECONDS, TRIGGER_LABELS as LABELS,
    WHEEL_SPIN_ZERO_RUNS, RESILIENCE_ZERO_RUNS, EXPLORER_EDIT_DISTANCE,
    ITERATIVE_EDIT_MIN, ITERATIVE_DEFAULT_THRESHOLD, ITERATIVE_THRESHOLDS,
)
```

Add the function:

```python
def detect_run_triggers_by_playground(runs):
    """Split `runs` into contiguous same-playground stretches and run
    detect_run_triggers on each, using that playground's Step-by-Step threshold
    (default when unlisted). `runs` is the list from compute_run_edit_distances.
    Returns [(trigger_type, global_run_index, detail)].

    Each stretch is an independent detect_run_triggers call, so every counter
    (zero streak, iterative count, re-arm flags) resets at a playground switch,
    and jumping back to an earlier playground starts fresh. Run indices are kept
    global via the stretch offset. Reads the playground with .get so runs built
    without the field collapse into one default-threshold stretch."""
    out = []
    i, n = 0, len(runs)
    while i < n:
        pg = runs[i].get("playground")
        j = i
        while j < n and runs[j].get("playground") == pg:
            j += 1
        edit_distances = [r["edit_distance"] for r in runs[i:j]]
        threshold = ITERATIVE_THRESHOLDS.get(pg, ITERATIVE_DEFAULT_THRESHOLD)
        for ttype, local_idx, detail in detect_run_triggers(
            edit_distances, iterative_threshold=threshold
        ):
            out.append((ttype, i + local_idx, detail))
        i = j
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_triggers_by_playground.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/triggers.py tests/test_triggers_by_playground.py
git commit -m "Add per-playground trigger segmentation (detect_run_triggers_by_playground)"
```

---

### Task 4: Wire the worker to the per-playground segmentation

**Files:**
- Modify: `app/pipeline/workers.py` (import at ~24, the trigger loop at ~91-99)
- Test: `tests/test_workers.py` (add one integration test)

**Interfaces:**
- Consumes: `detect_run_triggers_by_playground(runs)` from Task 3; `self._runs_cache["runs"]` now carrying `playground`.
- Produces: no signature change; `recompute_and_write` now fires triggers per playground.

- [ ] **Step 1: Write the failing integration test**

Add to `tests/test_workers.py`:

```python
def test_recompute_fires_step_by_step_at_the_playground_threshold():
    """RoverRescue's threshold is 3, so three real edits in RoverRescue fire the
    iterative trigger through the full worker path."""
    import json
    from app import db
    # Distinct workspaces so each run has edit_distance > 1.
    xmls = [
        '<xml><block type="a" id="1"></block></xml>',
        '<xml><block type="a" id="1"></block><block type="b" id="2"></block></xml>',
        '<xml><block type="a" id="1"></block><block type="b" id="2"></block>'
        '<block type="c" id="3"></block></xml>',
        '<xml><block type="a" id="1"></block><block type="b" id="2"></block>'
        '<block type="c" id="3"></block><block type="d" id="4"></block></xml>',
    ]
    w = workers.StudentWorker("s1")
    for i, x in enumerate(xmls):
        w.events.append({"event_type": "runProject", "ts": float(i),
                         "content": json.dumps({"playground": "RoverRescue",
                                                 "project": {"workspace": x}})})
    w.had_new_run = True
    w.recompute_and_write()
    fired = [t["trigger_type"] for t in db.triggers_feed(db.now() - __import__("datetime").timedelta(days=1))]
    assert "iterative" in fired
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_workers.py::test_recompute_fires_step_by_step_at_the_playground_threshold -v`
Expected: FAIL — the worker still calls the flat `detect_run_triggers` with the default threshold of 6, so three edits do not fire.

- [ ] **Step 3: Wire the worker to the segmentation entry point**

In `app/pipeline/workers.py`, update the import on line ~24:

```python
from app.pipeline.triggers import detect_run_triggers_by_playground, _disabled_types
```

Then in `recompute_and_write`, replace the run-count + trigger loop (the block that builds `edit_distances` and loops over `detect_run_triggers(edit_distances)`) with:

```python
        runs = self._runs_cache["runs"]
        run_count = len(runs)  # one entry per runProject

        # Momentary triggers fire once per qualifying run, evaluated per contiguous
        # playground stretch so a challenge switch resets every counter and applies
        # that playground's threshold. Deduped per type by run index (seeded from the
        # DB on rehydrate). Respects the disabled-triggers flag.
        for ttype, idx, detail in detect_run_triggers_by_playground(runs):
            if ttype in disabled or idx in self.fired[ttype]:
                continue
            run_ts = runs[idx].get("ts")
            at = datetime.fromtimestamp(run_ts, tz=timezone.utc) if run_ts else db.now()
            db.create_trigger(
                self.student_id, ttype,
                started_at=at, last_seen_at=at, resolved_at=at,
                detail={**detail, "run_index": idx})
            self.fired[ttype].add(idx)
```

- [ ] **Step 4: Run the new test, then the full suite**

Run: `.venv/bin/pytest tests/test_workers.py::test_recompute_fires_step_by_step_at_the_playground_threshold -v`
Expected: PASS

Run: `.venv/bin/pytest -q`
Expected: PASS. If any pre-existing test fails because it asserts the exact `runs` dict shape without `playground`, that is expected only where a test compares whole dicts — update that assertion to include `"playground"` (or assert on individual keys). The worker fixtures that build `_runs_cache` without a playground key keep passing, because `detect_run_triggers_by_playground` reads it with `.get`.

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/workers.py tests/test_workers.py
git commit -m "Fire run triggers per playground stretch in the worker"
```

---

### Task 5: Documentation touch-up

**Files:**
- Modify: `docs/concepts/write-path.md` (the Step-by-Step / triggers section)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the write-path trigger description**

In `docs/concepts/write-path.md`, in the trigger table / notes, add a sentence that the run sequence is sliced into contiguous same-playground stretches: each switch resets the baseline (the first run's `edit_distance` is `null`) and every trigger counts only within the current stretch, and Step-by-Step uses the per-playground threshold from `ITERATIVE_THRESHOLDS` (default 6). Keep the existing tone (no em-dashes, Title Case headings).

- [ ] **Step 2: Commit**

```bash
git add docs/concepts/write-path.md
git commit -m "Document playground-aware run analysis in the write path"
```

---

## Self-Review

**Spec coverage:** attribute runs to playground (Task 2), split into contiguous stretches (Tasks 2+3), hard reset at switch for all triggers (Task 2 nulls the baseline; Task 3's per-stretch calls reset counters), per-playground threshold with default fallback (Tasks 1+3), jump-back independence (Task 3 test), missing/garbled playground = continuation (Task 2 test), inactive unaffected (untouched — `evaluate` sweep is not changed), no schema/API/frontend change (all edits in `app/runs`, `app/pipeline`, `app/constants`), additive per-run `playground` (Task 2). Corrected constant keys (Task 1). Docs (Task 5). All covered.

**Placeholder scan:** every code and test step contains complete code; no TBD/TODO.

**Type consistency:** `compute_run_edit_distances` returns run dicts with `playground` (Task 2); `detect_run_triggers_by_playground(runs)` consumes that exact shape via `.get("playground")` (Task 3); the worker passes `self._runs_cache["runs"]` straight in (Task 4). `detect_run_triggers(edit_distances, iterative_threshold=...)` is unchanged and reused. Names match across tasks.

"""The strategy HMM pipeline -- end to end against the real model.pkl. This is
the actual machine-learning core: bucketed change-scores -> model.predict ->
latent strategy state per run."""
from app.strategy_hmm.pipeline import (
    bucket_change_score, compute_strategy_states,
)
from app.strategy_hmm.constants import REWRITE_THRESHOLD, OBS_LABELS


def _run_event(workspace_xml, ts):
    return {"event_type": "runProject",
            "content": {"project": {"workspace": workspace_xml}}, "ts": ts}


# --- bucketing (pure, threshold edges) -------------------------------------
def test_bucket_change_score_truth_table():
    assert bucket_change_score(None) is None
    assert bucket_change_score(0) == 0                       # identical
    assert bucket_change_score(REWRITE_THRESHOLD / 2) == 1   # small edit
    assert bucket_change_score(REWRITE_THRESHOLD) == 2       # at threshold -> rewrite
    assert bucket_change_score(0.99) == 2                    # big change


# --- pipeline shape --------------------------------------------------------
def test_no_runs_returns_empty():
    out = compute_strategy_states([{"event_type": "blockMoved", "ts": 1.0}])
    assert out["runs"] == [] and out["obs_labels"] == OBS_LABELS


def test_single_run_has_no_score_bucket_or_state():
    xml = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    out = compute_strategy_states([_run_event(xml, 1.0)])
    assert len(out["runs"]) == 1
    r0 = out["runs"][0]
    assert r0["change_score"] is None and r0["obs_bucket"] is None
    assert r0["hmm_state"] is None                            # first run can't be decoded


def test_identical_consecutive_runs_bucket_zero():
    xml = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    out = compute_strategy_states([_run_event(xml, 1.0), _run_event(xml, 2.0)])
    assert out["runs"][1]["change_score"] == 0
    assert out["runs"][1]["obs_bucket"] == 0


def test_full_decode_assigns_valid_states():
    a = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    b = ('<xml><block type="events_whenStarted" id="a">'
         '<next><block type="motor_spin" id="b"></block></next></block></xml>')
    out = compute_strategy_states([_run_event(a, 1.0), _run_event(a, 2.0),
                                   _run_event(b, 3.0)])
    states = [r["hmm_state"] for r in out["runs"]]
    assert states[0] is None                                  # first run undecoded
    assert all(s in OBS_LABELS for s in states[1:])           # rest are valid 0/1/2
    # the changed run registered a non-identical bucket
    assert out["runs"][2]["obs_bucket"] in (1, 2)


def test_run_with_string_json_content_is_parsed():
    import json
    xml = '<xml><block type="events_whenStarted" id="a"></block></xml>'
    ev = {"event_type": "runProject", "ts": 1.0,
          "content": json.dumps({"project": {"workspace": xml}})}   # content as a string
    assert len(compute_strategy_states([ev])["runs"]) == 1


def test_run_with_unparseable_content_still_counts():
    ev = {"event_type": "runProject", "ts": 1.0, "content": "{bad json"}
    out = compute_strategy_states([ev])
    assert len(out["runs"]) == 1                    # a run with an empty workspace

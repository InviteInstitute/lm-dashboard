from learner_models import compute_run_edit_distances

XA = '<xml><block type="events_whenStarted" id="a"></block></xml>'
XB = (
    '<xml><block type="events_whenStarted" id="a">'
    '<next><block type="motor_on" id="b"></block></next></block></xml>'
)


def _run(xml, playground, ts):
    content = {"project": {"workspace": xml}}
    if playground is not None:
        content["playground"] = playground
    return {"event_type": "runProject", "ts": ts, "content": content}


def test_runs_are_tagged_with_playground():
    runs = compute_run_edit_distances([_run(XA, "RoverRescue", 0.0), _run(XB, "RoverRescue", 1.0)])[
        "runs"
    ]
    assert [r["playground"] for r in runs] == ["RoverRescue", "RoverRescue"]


def test_first_run_of_a_new_playground_resets_edit_distance_to_none():
    # Two RoverRescue runs then a switch to CastleCrasherPlus. The switch run's
    # workspace differs from the previous run, but the distance must be None
    # because it has no predecessor *in its own playground*.
    runs = compute_run_edit_distances(
        [
            _run(XA, "RoverRescue", 0.0),
            _run(XB, "RoverRescue", 1.0),
            _run(XA, "CastleCrasherPlus", 2.0),
        ]
    )["runs"]
    assert runs[0]["edit_distance"] is None  # first run overall
    assert runs[1]["edit_distance"] is not None  # within the RoverRescue stretch
    assert runs[2]["edit_distance"] is None  # first run of the new stretch
    assert runs[2]["playground"] == "CastleCrasherPlus"


def test_missing_playground_continues_the_current_stretch():
    # Second run has no playground field -> it carries the previous name and is
    # NOT treated as a switch, so its distance is computed normally.
    runs = compute_run_edit_distances(
        [
            _run(XA, "RoverRescue", 0.0),
            _run(XB, None, 1.0),
        ]
    )["runs"]
    assert runs[1]["playground"] == "RoverRescue"
    assert runs[1]["edit_distance"] is not None

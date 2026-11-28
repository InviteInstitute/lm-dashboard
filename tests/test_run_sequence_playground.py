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

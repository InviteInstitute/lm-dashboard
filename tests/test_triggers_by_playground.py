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
    assert isinstance(detect_run_triggers_by_playground(runs), list)

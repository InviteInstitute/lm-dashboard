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

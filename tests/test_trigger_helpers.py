"""Trigger helper functions: idle formatting, the wheel-spin streak anchor, the
disabled-types reader, and the disabled-set parameter path."""
from datetime import timezone

from app import db
from app.pipeline import triggers


def test_fmt_idle_minutes_hours_days():
    assert triggers._fmt_idle(0) == "idle 0m"
    assert triggers._fmt_idle(120) == "idle 2m"
    assert triggers._fmt_idle(3 * 3600) == "idle 3h"
    assert triggers._fmt_idle(2 * 86400) == "idle 2d"
    assert triggers._fmt_idle(None) == "idle 0m"


def test_disabled_types_reads_meta():
    assert triggers._disabled_types() == set()
    db.set_meta("disabled_triggers", "inactive,big_change")
    assert triggers._disabled_types() == {"inactive", "big_change"}


def test_wheel_spin_started_walks_back_the_stuck_streak():
    base = 1_700_000_000
    state = {"runs": {"runs": [
        {"hmm_state": 1, "ts": base},
        {"hmm_state": 2, "ts": base + 60},     # streak starts here
        {"hmm_state": 2, "ts": base + 120},
    ]}}
    started = triggers._wheel_spin_started(state, fallback=db.now())
    assert started.tzinfo is not None
    assert started == __import__("datetime").datetime.fromtimestamp(base + 60, tz=timezone.utc)


def test_wheel_spin_started_falls_back_without_timestamps():
    fb = db.now()
    state = {"runs": {"runs": [{"hmm_state": 2, "ts": None}]}}
    assert triggers._wheel_spin_started(state, fallback=fb) == fb


def test_wheel_spin_started_falls_back_on_out_of_range_timestamp():
    fb = db.now()
    state = {"runs": {"runs": [{"hmm_state": 2, "ts": 10 ** 15}]}}   # year out of range
    assert triggers._wheel_spin_started(state, fallback=fb) == fb


def test_evaluate_accepts_an_explicit_disabled_set():
    """The daemon passes the disabled set it already fetched; a disabled type
    must not fire even though meta wasn't consulted."""
    db.upsert_student_state("s1", {
        "current_state": triggers.WHEEL_SPIN_STATE, "consecutive_stuck": 1,
        "last_event_time": db.now(), "runs": {"runs": [], "obs_labels": {}},
    })
    triggers.evaluate(disabled={"wheel_spin"})
    assert db.current_open_trigger("s1", "wheel_spin") is None

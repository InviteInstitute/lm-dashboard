"""Trigger helper functions: idle formatting, the disabled-types reader, and the
disabled-set parameter path."""
from datetime import timedelta

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
    db.set_meta("disabled_triggers", "inactive,explorer")
    assert triggers._disabled_types() == {"inactive", "explorer"}


def test_evaluate_accepts_an_explicit_disabled_set():
    """The daemon passes the disabled set it already fetched; a disabled type
    must not fire even though meta wasn't consulted."""
    old = db.now() - timedelta(seconds=triggers.INACTIVE_TRIGGER_SECONDS + 30)
    db.upsert_student_state("s1", {"last_event_time": old})
    triggers.evaluate(disabled={"inactive"})
    assert db.current_open_trigger("s1", "inactive") is None
